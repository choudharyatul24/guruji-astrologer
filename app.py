import streamlit as st
import tempfile
import os, pickle, subprocess, time, json, requests
from yt_dlp import YoutubeDL

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow   # ✅ FIXED
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload MediaFileUpload

# ═══════════════════════════════════════════
# 📁 PATHS & SESSION STATE
# ═══════════════════════════════════════════
PATHS = {
    "yt_acc": "accounts/youtube",
    "secret": "client_secret.json",
    "clips":  "clips",
    "output": "output_videos"
}
# --- YE FUNCTION ADD KARNA ZAROORI HAI ---
def get_google_secret_path():
    """Streamlit secrets se JSON nikal kar temporary file banata hai"""
    if "google" in st.secrets:
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w") as f:
                f.write(st.secrets["google"]["client_secret"])
                return f.name
        except Exception as e:
            st.error(f"Secret Error: {e}")
    return PATHS["secret"]
for p in PATHS.values():
    if "." not in os.path.basename(p):
        os.makedirs(p, exist_ok=True)
os.makedirs("accounts", exist_ok=True)

DEFAULTS = {
    "targets_yt": [], "targets_ig": [], "targets_fb": [],
    "video_ready": False, "detected_clips": [],
    "raw_path": "raw_input.mp4", "multi_videos": []
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ═══════════════════════════════════════════
# 📈 TRENDING TAGS
# ═══════════════════════════════════════════
TRENDING_TAGS = {
    "Astrology / Vashikaran": [
        "#astrology","#vashikaran","#loveproblemsolution","#loveback",
        "#blackmagic","#spiritualhealing","#astrologer","#jyotish",
        "#shorts","#viral","#trending","#reels","#astrologerji"
    ],
    "Motivation": [
        "#motivation","#success","#mindset","#hustle","#grind",
        "#positivity","#selfimprovement","#growthmindset",
        "#inspirational","#shorts","#viral","#trending","#reels"
    ],
    "Health / Fitness": [
        "#fitness","#health","#workout","#gym","#weightloss",
        "#healthylifestyle","#yoga","#diet","#shorts","#viral","#reels"
    ],
    "Tech / AI": [
        "#ai","#technology","#chatgpt","#tech","#coding",
        "#programming","#shorts","#viral","#trending","#reels"
    ],
    "Custom": []
}

# ═══════════════════════════════════════════
# 🔑 YOUTUBE AUTH
# ═══════════════════════════════════════════
def get_yt_credentials(channel_label):
    token_path = os.path.join(PATHS["yt_acc"], f"{channel_label}.pickle")
    creds = None
    if os.path.exists(token_path):
        with open(token_path, 'rb') as f:
            creds = pickle.load(f)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(token_path, 'wb') as f:
                pickle.dump(creds, f)
        except Exception:
            creds = None
    return creds

def login_yt(channel_label):
    APP_URL = "https://gurujiblast-5pefd83xlnpydtkb3wydut.streamlit.app/"
    token_path = os.path.join(PATHS["yt_acc"], f"{channel_label}.pickle")

    secret_file_path = get_google_secret_path()

    try:
        flow = Flow.from_client_secrets_file(
            secret_file_path,
            scopes=[
                'https://www.googleapis.com/auth/youtube.upload',
                'https://www.googleapis.com/auth/youtube.force-ssl'
            ],
            redirect_uri=APP_URL
        )

        auth_url, _ = flow.authorization_url(
            prompt='consent',
            access_type='offline',
            include_granted_scopes='true'
        )

        st.link_button(f"🚀 LOGIN YouTube: {channel_label.upper()}", auth_url)

        # ✅ Query params handle
        query_params = st.query_params

        if "code" in query_params:
            flow.fetch_token(code=query_params["code"])

            with open(token_path, 'wb') as f:
                pickle.dump(flow.credentials, f)

            st.success("✅ YouTube Account Connected Successfully!")
            st.rerun()

    except Exception as e:
        st.error(f"YT Login Error: {e}")

# ═══════════════════════════════════════════
# 🧹 WATERMARK REMOVAL
# ═══════════════════════════════════════════
def remove_watermark(input_path, output_path):
    corner_filters = (
        "delogo=x=0:y=0:w=280:h=110,"
        "delogo=x=iw-280:y=0:w=280:h=110,"
        "delogo=x=0:y=ih-130:w=280:h=130,"
        "delogo=x=iw-320:y=ih-220:w=320:h=220,"
        "delogo=x=(iw/2)-200:y=ih-90:w=400:h=90"
    )
    cmd = ['ffmpeg','-y','-i',input_path,'-vf',corner_filters,
           '-c:v','libx264','-preset','ultrafast','-c:a','aac',output_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode == 0:
        return True
    # Fallback blur
    blur_filter = (
        "[0:v]split=4[v0][v1][v2][v3];"
        "[v0]crop=280:110:0:0,boxblur=15:15[tl];"
        "[v1]crop=280:110:iw-280:0,boxblur=15:15[tr];"
        "[v2]crop=280:130:0:ih-130,boxblur=15:15[bl];"
        "[v3]crop=320:220:iw-320:ih-220,boxblur=15:15[br];"
        "[in][tl]overlay=0:0[t1];"
        "[t1][tr]overlay=W-280:0[t2];"
        "[t2][bl]overlay=0:H-130[t3];"
        "[t3][br]overlay=W-320:H-220[out]"
    )
    cmd2 = ['ffmpeg','-y','-i',input_path,
            '-filter_complex',blur_filter,'-map','[out]','-map','0:a',
            '-c:v','libx264','-preset','ultrafast','-c:a','aac',output_path]
    return subprocess.run(cmd2, capture_output=True, text=True).returncode == 0

# ═══════════════════════════════════════════
# ✂️ AUTO CLIP DETECTION
# ═══════════════════════════════════════════
def get_video_duration(path):
    cmd = ['ffprobe','-v','error','-show_entries','format=duration','-of','json',path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(json.loads(r.stdout)['format']['duration'])
    except Exception:
        return 0

def detect_best_moments(video_path, num_clips=7, clip_len=45):
    duration = get_video_duration(video_path)
    if duration == 0:
        return []
    candidate_times = set()

    # Scene changes
    r = subprocess.run([
        'ffmpeg','-i',video_path,
        '-vf','select=gt(scene\\,0.3),showinfo',
        '-f','null','-'
    ], capture_output=True, text=True)
    for line in r.stderr.splitlines():
        if 'pts_time' in line:
            try:
                t = float(line.split('pts_time:')[1].split()[0])
                candidate_times.add(round(t, 1))
            except Exception:
                pass

    # Audio loudness
    seg = 5
    loud_scores = []
    for i in range(int(duration // seg)):
        start = i * seg
        r2 = subprocess.run([
            'ffmpeg','-ss',str(start),'-t',str(seg),'-i',video_path,
            '-af','astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level',
            '-f','null','-'
        ], capture_output=True, text=True)
        rms = -60.0
        for line in r2.stderr.splitlines():
            if 'RMS_level' in line:
                try: rms = float(line.split('=')[1])
                except: pass
        loud_scores.append((start, rms))

    loud_scores.sort(key=lambda x: x[1], reverse=True)
    for start, _ in loud_scores[:int(num_clips * 1.5)]:
        candidate_times.add(round(start, 1))

    candidates = sorted(candidate_times)
    if not candidates:
        step = duration / (num_clips + 1)
        candidates = [round(i * step, 1) for i in range(1, num_clips + 1)]

    selected, last_end = [], -clip_len
    for t in candidates:
        start = max(0, t - 5)
        end   = min(duration, start + clip_len)
        if start >= last_end and len(selected) < num_clips:
            selected.append((round(start,1), round(end,1)))
            last_end = end

    selected.sort()
    return selected[:num_clips]

def extract_clip(video_path, start, end, out_path):
    cmd = ['ffmpeg','-y','-ss',str(start),'-to',str(end),'-i',video_path,
           '-c:v','libx264','-preset','ultrafast','-c:a','aac',
           '-avoid_negative_ts','make_zero', out_path]
    return subprocess.run(cmd, capture_output=True, text=True).returncode == 0

# ═══════════════════════════════════════════
# 🎬 VIDEO BRANDING
# Top text = custom headline
# Bottom = Name + Phone number (always shown)
# ═══════════════════════════════════════════
def brand_video(input_p, output_p, h_txt, owner_name, owner_phone):
    def safe(s):
        return s.replace(":", "\\:").replace("'","").replace('"',"").replace("+","\\+")

    h_safe     = safe(h_txt)
    name_safe  = safe(owner_name)
    phone_safe = safe(owner_phone)

    vf = (
        # Resize to 9:16 Shorts format
        f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        # Top dark bar
        f"drawbox=y=0:color=black@0.85:width=iw:height=300:t=fill,"
        # Bottom dark bar
        f"drawbox=y=ih-280:color=black@0.85:width=iw:height=280:t=fill,"
        # Top headline text
        f"drawtext=text='{h_safe}':x=(w-text_w)/2:y=80:fontsize=82:"
        f"fontcolor=gold:borderw=3:bordercolor=black,"
        # Owner name (bottom left area)
        f"drawtext=text='{name_safe}':x=(w-text_w)/2:y=h-240:fontsize=68:"
        f"fontcolor=white:borderw=2:bordercolor=black,"
        # Phone number (below name)
        f"drawtext=text='{phone_safe}':x=(w-text_w)/2:y=h-155:fontsize=72:"
        f"fontcolor=yellow:borderw=3:bordercolor=black"
    )

    cmd = ['ffmpeg','-y','-i',input_p,'-vf',vf,
           '-c:v','libx264','-preset','ultrafast',
           '-c:a','aac','-t','59', output_p]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        st.error(f"Branding error: {r.stderr[-300:]}")
    return r.returncode == 0

# ═══════════════════════════════════════════
# 🚀 YOUTUBE UPLOAD
# ═══════════════════════════════════════════
def upload_youtube(video_path, title, channel_label, tags_list, comment_txt):
    try:
        creds = get_yt_credentials(channel_label)
        if not creds:
            return f"Error: Token expired for {channel_label}. Re-login karein."
        yt = build('youtube','v3',credentials=creds)
        body = {
            'snippet': {
                'title': f"{title} {' '.join(tags_list[:4])}",
                'description': f"{title}\n\n{' '.join(tags_list)}",
                'tags': [t.replace('#','') for t in tags_list],
                'categoryId': '22', 'defaultLanguage': 'hi'
            },
            'status': {'privacyStatus':'public','selfDeclaredMadeForKids':False}
        }
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
        res   = yt.videos().insert(part='snippet,status',body=body,media_body=media).execute()
        v_id  = res.get('id')
        if v_id and comment_txt:
            time.sleep(2)
            yt.commentThreads().insert(part="snippet", body={
                "snippet":{"videoId":v_id,
                           "topLevelComment":{"snippet":{"textOriginal":comment_txt}}}
            }).execute()
        return v_id
    except Exception as e:
        return f"Error: {e}"

# ═══════════════════════════════════════════
# 📘 FACEBOOK UPLOAD
# ═══════════════════════════════════════════
def upload_facebook(video_path, title, description, page_id, access_token):
    try:
        url = f"https://graph.facebook.com/v19.0/{page_id}/videos"
        with open(video_path,'rb') as vf:
            res = requests.post(url, data={
                "title":title,"description":description,
                "published":"true","access_token":access_token
            }, files={"source":vf})
        data = res.json()
        return data.get("id", f"Error: {data}")
    except Exception as e:
        return f"Error: {e}"

# ═══════════════════════════════════════════
# 📱 INSTAGRAM UPLOAD
# ═══════════════════════════════════════════
def upload_instagram(video_path, caption, ig_user_id, access_token, video_public_url=""):
    try:
        if not video_public_url:
            return "IG_NO_URL"
        r1 = requests.post(
            f"https://graph.facebook.com/v19.0/{ig_user_id}/media",
            params={"media_type":"REELS","video_url":video_public_url,
                    "caption":caption,"access_token":access_token}
        ).json()
        container_id = r1.get("id")
        if not container_id:
            return f"Error container: {r1}"
        time.sleep(35)
        r2 = requests.post(
            f"https://graph.facebook.com/v19.0/{ig_user_id}/media_publish",
            params={"creation_id":container_id,"access_token":access_token}
        ).json()
        return r2.get("id", f"Error publish: {r2}")
    except Exception as e:
        return f"Error: {e}"

# ═══════════════════════════════════════════
# 🔁 CORE PIPELINE (one video → process → upload everywhere)
# ═══════════════════════════════════════════
def process_and_upload(
    video_path, clip_idx, clip_start, clip_end,
    h_text, owner_name, owner_phone,
    remove_wm, selected_tags, comment_text,
    yt_targets, ig_targets, fb_targets
):
    log = []
    clip_title = f"{h_text} - Part {clip_idx+1}"

    raw_clip   = os.path.join(PATHS["clips"],  f"clip{clip_idx}_raw.mp4")
    clean_clip = os.path.join(PATHS["clips"],  f"clip{clip_idx}_clean.mp4")
    final_clip = os.path.join(PATHS["output"], f"clip{clip_idx}_final.mp4")

    # 1. Extract
    if clip_start is not None:
        ok = extract_clip(video_path, clip_start, clip_end, raw_clip)
        if not ok:
            st.error(f"Clip {clip_idx+1} extract fail!")
            return log
        work = raw_clip
    else:
        work = video_path  # direct video (no clipping needed)

    # 2. Watermark remove
    if remove_wm:
        with st.spinner("🧹 Watermark hata raha hai..."):
            ok2 = remove_watermark(work, clean_clip)
            work = clean_clip if ok2 else work
            if not ok2: st.warning("WM removal fail, original use ho raha hai.")

    # 3. Brand (headline + name + phone)
    with st.spinner("✏️ Naam aur number add ho raha hai..."):
        if not brand_video(work, final_clip, h_text, owner_name, owner_phone):
            st.error("Branding fail!")
            return log

    # 4. Upload — YouTube
    for ch in yt_targets:
        with st.spinner(f"▶️ YouTube upload: {ch}..."):
            res = upload_youtube(final_clip, clip_title, ch, selected_tags, comment_text)
            if res and "Error" not in str(res):
                link = f"https://youtube.com/shorts/{res}"
                st.success(f"✅ YouTube {ch} → [View Short]({link})")
                log.append(("YouTube", ch, "✅", link))
            else:
                st.error(f"❌ YouTube {ch}: {res}")
                log.append(("YouTube", ch, "❌", str(res)))

    # 5. Upload — Instagram
    for ig in ig_targets:
        acc_f = f"accounts/ig_{ig}.json"
        if os.path.exists(acc_f):
            with open(acc_f) as f: ig_data = json.load(f)
            base_url = ig_data.get("base_url","")
            pub_url  = f"{base_url}clip{clip_idx}_final.mp4" if base_url else ""
            with st.spinner(f"📸 Instagram upload: {ig}..."):
                res = upload_instagram(
                    final_clip,
                    f"{clip_title}\n{' '.join(selected_tags)}",
                    ig_data["user_id"], ig_data["token"], pub_url
                )
                if res == "IG_NO_URL":
                    st.warning(f"📸 {ig}: Public URL set nahi. Sidebar mein daalo.")
                elif "Error" not in str(res):
                    st.success(f"✅ Instagram {ig} → ID: {res}")
                    log.append(("Instagram", ig, "✅", str(res)))
                else:
                    st.error(f"❌ Instagram {ig}: {res}")
                    log.append(("Instagram", ig, "❌", str(res)))

    # 6. Upload — Facebook
    for fb in fb_targets:
        acc_f = f"accounts/fb_{fb}.json"
        if os.path.exists(acc_f):
            with open(acc_f) as f: fb_data = json.load(f)
            with st.spinner(f"📘 Facebook upload: {fb}..."):
                res = upload_facebook(
                    final_clip, clip_title,
                    f"{clip_title}\n{' '.join(selected_tags)}",
                    fb_data["page_id"], fb_data["token"]
                )
                if "Error" not in str(res):
                    st.success(f"✅ Facebook {fb} → ID: {res}")
                    log.append(("Facebook", fb, "✅", str(res)))
                else:
                    st.error(f"❌ Facebook {fb}: {res}")
                    log.append(("Facebook", fb, "❌", str(res)))

    # Cleanup temp
    for tmp in [raw_clip, clean_clip]:
        if os.path.exists(tmp) and tmp != final_clip:
            os.remove(tmp)

    return log

# ═══════════════════════════════════════════════════
# 🎨 UI
# ═══════════════════════════════════════════════════
st.set_page_config(page_title="GURUJI BLAST v10", layout="wide", page_icon="🔱")

# ── SIDEBAR ──
with st.sidebar:
    st.header("⚙️ ACCOUNT MANAGER")
    tab_yt, tab_ig, tab_fb = st.tabs(["▶️ YouTube","📸 Instagram","📘 Facebook"])

    with tab_yt:
        new_yt = st.text_input("Channel Name", key="new_yt")
        if st.button("➕ Add YouTube Account"):
            if new_yt.strip(): login_yt(new_yt.strip())
            else: st.warning("Name daalo!")
        yt_accounts = [f.replace(".pickle","") for f in os.listdir(PATHS['yt_acc']) if f.endswith(".pickle")]
        if yt_accounts:
            st.success(f"✅ {len(yt_accounts)} account(s)")
            for a in yt_accounts: st.caption(f"• {a}")

    with tab_ig:
        st.info("Instagram Business account + Graph API token chahiye.")
        ig_uid  = st.text_input("Instagram User ID",  key="ig_uid")
        ig_tok  = st.text_input("Access Token",        key="ig_tok",  type="password")
        ig_url  = st.text_input("Public Video Base URL", key="ig_url")
        ig_name = st.text_input("Label",               key="ig_name")
        if st.button("💾 Save Instagram"):
            if ig_uid and ig_tok and ig_name:
                with open(f"accounts/ig_{ig_name}.json","w") as f:
                    json.dump({"user_id":ig_uid,"token":ig_tok,"base_url":ig_url},f)
                st.success("✅ Saved!")

    with tab_fb:
        st.info("Facebook Page Access Token chahiye.")
        fb_pid  = st.text_input("Page ID",            key="fb_pid")
        fb_tok  = st.text_input("Page Access Token",  key="fb_tok", type="password")
        fb_name = st.text_input("Label",              key="fb_name")
        if st.button("💾 Save Facebook"):
            if fb_pid and fb_tok and fb_name:
                with open(f"accounts/fb_{fb_name}.json","w") as f:
                    json.dump({"page_id":fb_pid,"token":fb_tok},f)
                st.success("✅ Saved!")

    st.divider()
    st.caption("⚠️ client_secret.json kabhi share mat karo!")

# ── MAIN ──
st.title("🔱 GURUJI HYBRID BLAST v10.0")
st.caption("Video → Watermark Remove → Naam+Number Brand → YouTube + Instagram + Facebook — Ek Click Mein! 🚀")

# ════════════════════════════════════════
# STEP 1: OWNER INFO (Naam + Number)
# ════════════════════════════════════════
st.subheader("👤 Step 1: Aapki Details (Video pe dikhegi)")
col_n, col_p = st.columns(2)
with col_n:
    owner_name  = st.text_input("📛 Aapka Naam",   value="Rahul Sadak")
with col_p:
    owner_phone = st.text_input("📞 Phone Number", value="+91 87509334718")

st.info(f"✅ Har video pe neeche dikhega: **{owner_name}** | **{owner_phone}**")

# ════════════════════════════════════════
# STEP 2: VIDEO SOURCE (Single ya Multiple)
# ════════════════════════════════════════
st.subheader("📹 Step 2: Video(s) Upload Karo")
upload_mode = st.radio("Mode", ["Single Video / Link", "Multiple Videos (Bulk)"], horizontal=True)

video_queue = []  # list of file paths to process

if upload_mode == "Single Video / Link":
    source = st.radio("Source", ["YouTube Link","Device se Upload"], horizontal=True)
    raw_path = st.session_state.raw_path

    if source == "YouTube Link":
        v_url = st.text_input("🔗 YouTube Link")
        if v_url and st.button("⬇️ Download"):
            with st.spinner("Downloading..."):
                try:
                    with YoutubeDL({'outtmpl': raw_path,
                                    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                                    'merge_output_format': 'mp4'}) as ydl:
                        ydl.download([v_url])
                    st.session_state.video_ready = True
                    st.success("✅ Video Ready!")
                except Exception as e:
                    st.error(f"Download Error: {e}")
    else:
        u_file = st.file_uploader("Video Upload", type=["mp4","mov","avi"])
        if u_file:
            with open(raw_path,"wb") as f: f.write(u_file.getbuffer())
            st.session_state.video_ready = True
            st.success("✅ Video Uploaded!")

    if st.session_state.video_ready and os.path.exists(raw_path):
        dur = get_video_duration(raw_path)
        st.info(f"📊 Duration: {int(dur//60)}m {int(dur%60)}s")
        st.video(raw_path)
        video_queue = [raw_path]

else:  # Multiple Videos
    multi_files = st.file_uploader(
        "📂 Multiple Videos Upload Karo (sab ek saath select karo)",
        type=["mp4","mov","avi"],
        accept_multiple_files=True
    )
    if multi_files:
        st.session_state.multi_videos = []
        for i, mf in enumerate(multi_files):
            p = os.path.join(PATHS["clips"], f"multi_{i}_{mf.name}")
            with open(p,"wb") as f: f.write(mf.getbuffer())
            st.session_state.multi_videos.append(p)
        st.success(f"✅ {len(multi_files)} videos ready!")
        for p in st.session_state.multi_videos:
            st.video(p)
        video_queue = st.session_state.multi_videos

# ════════════════════════════════════════
# STEP 3: WATERMARK
# ════════════════════════════════════════
st.subheader("🧹 Step 3: Watermark Remove")
remove_wm = st.toggle("Watermark hatao", value=True)

# ════════════════════════════════════════
# STEP 4: AUTO CLIP (only for single long video)
# ════════════════════════════════════════
if upload_mode == "Single Video / Link":
    st.subheader("✂️ Step 4: Auto Clip Detection (Long video ke liye)")
    use_clips = st.toggle("Long video se best clips auto-cut karo", value=False)
    if use_clips:
        col_a, col_b = st.columns(2)
        with col_a: num_clips   = st.slider("Clips count",          3, 10, 7)
        with col_b: clip_length = st.slider("Clip length (seconds)",15, 59, 45)

        if st.button("🔍 Best Moments Dhundo!", disabled=not st.session_state.video_ready):
            with st.spinner("Video analyze ho rahi hai... (1-2 min)"):
                clips = detect_best_moments(raw_path, num_clips, clip_length)
                st.session_state.detected_clips = clips
            st.success(f"✅ {len(clips)} moments mili!")

        if st.session_state.detected_clips:
            st.markdown("**Clips (adjust kar sakte ho):**")
            edited = []
            for i,(s,e) in enumerate(st.session_state.detected_clips):
                c1,c2 = st.columns(2)
                with c1: ns = st.number_input(f"Clip {i+1} Start(s)", value=s, step=1.0, key=f"cs{i}")
                with c2: ne = st.number_input(f"Clip {i+1} End(s)",   value=e, step=1.0, key=f"ce{i}")
                edited.append((ns,ne))
            st.session_state.detected_clips = edited
    else:
        st.session_state.detected_clips = []
else:
    st.subheader("✂️ Step 4: Auto Clip")
    st.info("Multiple mode mein har video directly upload hogi (no clipping).")
    use_clips = False

# ════════════════════════════════════════
# STEP 5: HEADLINE TEXT
# ════════════════════════════════════════
st.subheader("✏️ Step 5: Video Headline")
h_text = st.text_input("💎 TOP TEXT (Headline)", "LOVE PROBLEM SOLUTION")
st.caption(f"Video pe dikhega → TOP: {h_text} | BOTTOM: {owner_name} | {owner_phone}")

# ════════════════════════════════════════
# STEP 6: SEO TAGS
# ════════════════════════════════════════
st.subheader("📈 Step 6: SEO Tags")
niche = st.selectbox("Niche", list(TRENDING_TAGS.keys()))
if niche == "Custom":
    raw_tags = st.text_area("Custom tags (ek per line)", "#tag1\n#tag2")
    selected_tags = [t.strip() for t in raw_tags.splitlines() if t.strip()]
else:
    selected_tags = st.multiselect("Tags:", TRENDING_TAGS[niche], default=TRENDING_TAGS[niche])
comment_text = st.text_input("💬 Auto-Comment", f"📲 {owner_name} se contact karein | {owner_phone} | #shorts #viral")

# ════════════════════════════════════════
# STEP 7: PLATFORMS (ONE CLICK ALL THREE)
# ════════════════════════════════════════
st.subheader("🎯 Step 7: Platforms — Ek Click Mein Teeno!")

yt_accounts = [f.replace(".pickle","") for f in os.listdir(PATHS['yt_acc']) if f.endswith(".pickle")]
ig_accounts = [f[3:-5] for f in os.listdir("accounts") if f.startswith("ig_") and f.endswith(".json")]
fb_accounts = [f[3:-5] for f in os.listdir("accounts") if f.startswith("fb_") and f.endswith(".json")]

col_yt, col_ig, col_fb = st.columns(3)
with col_yt:
    st.markdown("**▶️ YouTube**")
    yt_sel = st.multiselect("Channels", yt_accounts or ["(Add in sidebar)"], default=st.session_state.targets_yt, key="yt_sel")
with col_ig:
    st.markdown("**📸 Instagram**")
    ig_sel = st.multiselect("Accounts", ig_accounts or ["(Add in sidebar)"], key="ig_sel")
with col_fb:
    st.markdown("**📘 Facebook**")
    fb_sel = st.multiselect("Pages", fb_accounts or ["(Add in sidebar)"], key="fb_sel")

# ════════════════════════════════════════
# BLAST BUTTON
# ════════════════════════════════════════
st.markdown("---")

# Summary preview before blast
if video_queue or st.session_state.detected_clips:
    clips_to_do = st.session_state.detected_clips if use_clips and st.session_state.detected_clips else None
    n_videos = len(clips_to_do) if clips_to_do else len(video_queue) if video_queue else 0
    n_platforms = len([x for x in [yt_sel, ig_sel, fb_sel] if x])
    total_uploads = n_videos * (len(yt_sel) + len(ig_sel) + len(fb_sel))
    if n_videos > 0:
        st.info(f"📊 **Preview:** {n_videos} video(s) × {len(yt_sel)+len(ig_sel)+len(fb_sel)} platform accounts = **{total_uploads} total uploads**")

if st.button("🔥 EK CLICK MEIN TEENO PE UPLOAD KAR!", use_container_width=True, type="primary"):
    # Validations
    if not video_queue and not st.session_state.video_ready:
        st.error("❌ Pehle video upload karo!")
    elif use_clips and not st.session_state.detected_clips:
        st.error("❌ Pehle 'Best Moments Dhundo!' dabao!")
    elif not any([yt_sel, ig_sel, fb_sel]):
        st.error("❌ Koi platform/channel select nahi kiya!")
    else:
        all_log = []

        # Determine jobs
        if use_clips and st.session_state.detected_clips:
            # Long video → auto clips
            jobs = [(raw_path, i, s, e)
                    for i,(s,e) in enumerate(st.session_state.detected_clips)]
        elif video_queue:
            # Direct videos (single or multiple)
            jobs = [(vp, i, None, None) for i, vp in enumerate(video_queue)]
        else:
            jobs = []

        prog = st.progress(0, "Shuru ho raha hai...")

        for job_idx, (vpath, cidx, cstart, cend) in enumerate(jobs):
            label = f"Clip {cidx+1}" if cstart is not None else os.path.basename(vpath)
            st.markdown(f"### 🎬 Processing: {label} ({job_idx+1}/{len(jobs)})")

            result = process_and_upload(
                vpath, cidx, cstart, cend,
                h_text, owner_name, owner_phone,
                remove_wm, selected_tags, comment_text,
                yt_sel, ig_sel, fb_sel
            )
            all_log.extend(result)
            prog.progress((job_idx+1)/len(jobs), f"{job_idx+1}/{len(jobs)} done!")

        # Final Report
        st.markdown("---")
        st.markdown("## 📊 Final Report")
        success = [x for x in all_log if x[2]=="✅"]
        failed  = [x for x in all_log if x[2]=="❌"]
        st.markdown(f"**✅ Success: {len(success)}  |  ❌ Failed: {len(failed)}**")
        for platform, channel, status, info in all_log:
            icon = "▶️" if platform=="YouTube" else "📸" if platform=="Instagram" else "📘"
            detail = f"[View]({info})" if info.startswith("http") else info
            st.write(f"{status} {icon} **{platform}** | {channel} → {detail}")

        st.balloons()
        st.session_state.video_ready   = False
        st.session_state.detected_clips = []
        st.session_state.multi_videos   = []
        st.success(f"🎉 Blast complete! {len(success)} uploads successful!")
