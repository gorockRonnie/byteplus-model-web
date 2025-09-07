import os
import time
import json
import base64
import requests
import threading
import streamlit as st
from streamlit_autorefresh import st_autorefresh
from tos import TosClientV2
from io import BytesIO
import tos

# ===== Default Base API =====
DEFAULT_BASE_API = os.getenv("ARK_BASE_URL", "https://ark.ap-southeast.bytepluses.com/api/v3")
VIDEO_URL = f"{DEFAULT_BASE_API}/contents/generations/tasks"
VIDEO_TASK_GET = VIDEO_URL + "/{task_id}"

# ===== BytePlus TOS Config =====
TOS_AK = os.getenv("TOS_AK")
TOS_SK = os.getenv("TOS_SK")
TOS_ENDPOINT = "https://tos-ap-southeast-1.bytepluses.com"
TOS_REGION = "ap-southeast-1"
TOS_BUCKET = "modelarkbucket"

if TOS_AK and TOS_SK:
    tos_client = tos.TosClientV2(TOS_AK, TOS_SK, TOS_ENDPOINT, TOS_REGION)
else:
    tos_client = None
    st.warning("⚠️ TOS_AK or TOS_SK is not set，can't upload local image")

# ===== Streamlit Config =====
st.set_page_config(page_title="Model Hub UI (BytePlus)", layout="wide")

# ===== Helpers =====
def auth_headers(api_key: str, is_json=True):
    headers = {"Authorization": f"Bearer {api_key}"}
    if is_json:
        headers["Content-Type"] = "application/json"
    return headers

# ===== Chat SSE Stream =====
def sse_chat_stream(model: str, api_key: str, messages: list, temperature: float = 0.7):
    payload = {"model": model, "messages": messages, "temperature": temperature, "stream": True}
    try:
        with requests.post(f"{DEFAULT_BASE_API}/chat/completions", headers=auth_headers(api_key), json=payload, stream=True, timeout=600) as r:
            if r.status_code >= 400:
                try: err = r.json()
                except: err = r.text
                raise Exception(f"Chat API returned {r.status_code}: {err}")
            for line in r.iter_lines(decode_unicode=False):
                if not line:
                    continue
                line = line.decode("utf-8").strip()  # 强制 UTF-8
                if line.startswith("data: "):
                    data_str = line[len("data: "):]
                    if data_str == "[DONE]":
                        break
                    try:
                        event = json.loads(data_str)
                        if "choices" in event and event["choices"]:
                            delta = event["choices"][0].get("delta") or event["choices"][0].get("message", {})
                            if "content" in delta and delta["content"] is not None:
                                yield delta["content"]
                    except json.JSONDecodeError:
                        continue
    except requests.RequestException as e:
        raise Exception(f"Network error when calling Chat API: {e}")

# ===== Image Generation =====
def create_image(model: str, api_key: str, prompt: str, size: str = "1024x1024", n: int = 1):
    IMG_URL = f"{DEFAULT_BASE_API}/images/generations"
    payload = {"model": model, "prompt": prompt, "n": n, "size": size}
    resp = requests.post(IMG_URL, headers=auth_headers(api_key), json=payload, timeout=600)
    if resp.status_code >= 400:
        try: err = resp.json()
        except: err = resp.text
        raise Exception(f"Image API returned {resp.status_code}: {err}")
    data = resp.json()
    images = []
    for item in data.get("data", []):
        if "b64_json" in item:
            images.append(("b64", item["b64_json"]))
        elif "url" in item:
            images.append(("url", item["url"]))
    return images

# ===== Video Generation =====
def create_video_task_t2v(model: str, api_key: str, prompt_with_params: str):
    payload = {"model": model, "content": [{"type": "text", "text": prompt_with_params}]}
    resp = requests.post(VIDEO_URL, headers=auth_headers(api_key), json=payload, timeout=120)
    if resp.status_code >= 400:
        try: err = resp.json()
        except: err = resp.text
        raise Exception(f"Video create (T2V) returned {resp.status_code}: {err}")
    return resp.json()

def create_video_task_i2v(model: str, api_key: str, prompt_with_params: str, image_url: str):
    content = [{"type": "text", "text": prompt_with_params},
               {"type": "image_url", "image_url": {"url": image_url}}]
    payload = {"model": model, "content": content}
    resp = requests.post(VIDEO_URL, headers=auth_headers(api_key), json=payload, timeout=120)
    if resp.status_code >= 400:
        try: err = resp.json()
        except: err = resp.text
        raise Exception(f"Video create (I2V) returned {resp.status_code}: {err}")
    return resp.json()

def get_video_task(api_key: str, task_id: str):
    url = VIDEO_TASK_GET.format(task_id=task_id)
    resp = requests.get(url, headers=auth_headers(api_key), timeout=60)
    if resp.status_code >= 400:
        try: err = resp.json()
        except: err = resp.text
        raise Exception(f"Video task GET returned {resp.status_code}: {err}")
    return resp.json()

def find_video_url(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            res = find_video_url(v)
            if res: return res
    elif isinstance(obj, list):
        for it in obj:
            res = find_video_url(it)
            if res: return res
    elif isinstance(obj, str):
        if obj.startswith("http") and (".mp4" in obj or "video" in obj.lower()):
            return obj
    return None

def upload_image_to_tos(uploaded_file):
    if not tos_client:
        raise Exception("TOS client is not initialized. Please set TOS_AK and TOS_SK environment variables.")

    uploaded_bytes = uploaded_file.read()
    uploaded_file.seek(0)
    object_key = f"uploads/{int(time.time())}_{uploaded_file.name}"
    try:
        resp = tos_client.put_object(TOS_BUCKET, object_key, content=uploaded_bytes)
        if hasattr(resp, "status_code") and resp.status_code != 200:
            raise Exception(f"TOS put_object returned status {resp.status_code}")
        
        # Generate presigned URL
        url = client.pre_signed_url(HttpMethodType.Http_Method_Get, bucket_name, object_key)
        return url
    except Exception as e:
        raise Exception(f"Failed to upload image to TOS: {e}")

# ===== Session State Defaults =====
for key, default in {
    "stop_chat": False,
    "chat_history": [],
    "video_task_queue": [],
    "video_thread_running": False,
    "video_stop_event": threading.Event()
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ===== Sidebar =====
st.sidebar.title("Configurations")
api_key = st.sidebar.text_input("API Key", type="password", value=os.getenv("ARK_API_KEY", ""))
chat_model = st.sidebar.text_input("Chat Model ID", value="seed-1-6-250615")
image_model = st.sidebar.text_input("Image Model ID", value="seedream-3-0-t2i-250415")
# video_model_t2v = st.sidebar.text_input("Video Model ID (T2V)", value="seedance-1-0-pro-250528")
# video_model_i2v = st.sidebar.text_input("Video Model ID (I2V)", value="seedance-1-0-pro-250528")
video_model = st.sidebar.text_input("Video Model ID", value="seedance-1-0-pro-250528")

# ===== Tabs =====
tab_chat, tab_image, tab_video = st.tabs(["💬 Chat", "🖼️ Image Generation", "🎬 Video Generation"])

# ===== Chat Tab =====
with tab_chat:
    st.subheader("Chat")
    col_in, col_out = st.columns([1,1.2])
    with col_in:
        system_prompt = st.text_area("System Prompt", "You are a helpful assistant.", height=100)
        user_input = st.text_area("User Message", height=150)
        temp = st.slider("Temperature", 0.0, 2.0, 0.7)
        go_chat = st.button("Send", key="send_chat")
        clear_chat = st.button("Clear Chat", key="clear_chat")
    with col_out:
        chat_box = st.container()
        if clear_chat:
            st.session_state.chat_history = []
            st.rerun()

    if st.session_state.chat_history:
        for msg in st.session_state.chat_history:
            with chat_box.chat_message(msg["role"]):
                st.markdown(msg["content"])

    if go_chat:
        if not api_key or not chat_model:
            st.error("Missing API key or Chat Model ID")
        elif not user_input.strip():
            st.warning("Please enter a message.")
        else:
            st.session_state.chat_history.append({"role": "user", "content": user_input.strip()})
            with chat_box.chat_message("user"):
                st.markdown(user_input.strip())
            messages = []
            if system_prompt.strip():
                messages.append({"role": "system", "content": system_prompt.strip()})
            messages.extend(st.session_state.chat_history)
            with chat_box.chat_message("assistant"):
                response_box = st.empty()
                acc_response = ""
                try:
                    for token in sse_chat_stream(chat_model, api_key, messages, temp):
                        acc_response += token
                        response_box.markdown(acc_response + "▌")
                    response_box.markdown(acc_response)
                    st.session_state.chat_history.append({"role": "assistant", "content": acc_response})
                except Exception as e:
                    st.error(f"Chat request failed:\n{e}")

# ===== Image Tab =====
with tab_image:
    st.subheader("Image Generation")
    col_left, col_right = st.columns([1,1.2])
    with col_left:
        prompt = st.text_area("Prompt", height=150, key="img_prompt")
        size = st.selectbox("Size", ["1024x1024(1:1)","864x1152(3:4)","1152x864(4:3)","1280x720(16:9)","720x1280 (9:16)","832x1248 (2:3)","1248x832 (3:2)","1512x648 (21:9)"])
        n = st.number_input("Number of Images",1,4,1)
        go_img = st.button("Generate Image")
    with col_right:
        out_area = st.container()

    if go_img:
        if not api_key or not image_model:
            st.error("Missing API key or Image Model ID")
        elif not prompt.strip():
            st.warning("Please enter a prompt.")
        else:
            with st.spinner("Generating image(s), please wait..."):
                try:
                    imgs = create_image(image_model, api_key, prompt, size=size, n=n)
                    for kind,val in imgs:
                        if kind=="b64":
                            out_area.image(base64.b64decode(val))
                        else:
                            out_area.image(val)
                except Exception as e:
                    st.error(f"Image generation failed: {e}")

# ===== Video Tab =====
with tab_video:
    st.subheader("Video Generation")
    col_cfg, col_out = st.columns([1,1.2])

    with col_cfg:
        mode = st.radio("Mode", ["Text-to-Video (T2V)", "Image-to-Video (I2V)"])
        prompt_text = st.text_area("Prompt (scene description)", height=120)
        resolution = st.selectbox("Resolution", ["480p", "720p", "1080p"], index=1)
        duration = st.number_input("Duration (seconds)", 1, 30, value=5)
        poll_interval = st.slider("Poll interval (seconds)", 1, 30, 5, 1)

        uploaded_file = None
        image_url_input = ""
        if mode == "Image-to-Video (I2V)":
            input_type = st.radio("Select Image Input Type", ["Public URL", "Upload Local Image"], index=0)
            if input_type == "Public URL":
                image_url_input = st.text_input("Public Image URL")
            else:
                uploaded_file = st.file_uploader("Upload Image", type=["png","jpg","jpeg","webp"])
                if uploaded_file:
                    st.image(uploaded_file, caption="Local preview")
                    if not tos_client:
                        st.error("TOS client is not initialized. Cannot upload local image.")
                        uploaded_file = None  # Uploading restricted

        go_video = st.button("Create Task")

    with col_out:
        video_status_box = st.container()

    if go_video:
        if not api_key or not video_model or not prompt_text.strip():
            st.error("Missing required inputs")
        elif mode == "Image-to-Video (I2V)" and not (image_url_input.strip() or uploaded_file):
            st.error("For I2V, provide either public image URL or upload a local image.")
        else:
            with st.spinner("Submitting video generation task..."):
                try:
                    prompt_with_params = f"{prompt_text.strip()} --resolution {resolution} --duration {duration}"
                    image_url = None

                    # Same model for t2v and i2v
                    if mode == "Text-to-Video (T2V)":
                        create_resp = create_video_task_t2v(video_model, api_key, prompt_with_params)
                    else:
                        if uploaded_file:
                            image_url = upload_image_to_tos(uploaded_file)
                        else:
                            image_url = image_url_input.strip()
                        create_resp = create_video_task_i2v(video_model, api_key, prompt_with_params, image_url)

                    task_id = create_resp.get("id") or create_resp.get("task_id")
                    if task_id:
                        st.session_state.video_task_queue.append({
                            "task_id": task_id,
                            "prompt": prompt_text.strip(),
                            "mode": mode,
                            "image_url": image_url,
                            "status": "pending",
                            "video_url": None
                        })
                    else:
                        st.error(f"Failed to get task_id from response: {create_resp}")
                except Exception as e:
                    st.error(f"Failed to create video task: {e}")

    # ===== Pending Tasks Auto Refresh =====
    pending_tasks_exist = any(
        task["status"] not in ("succeeded", "failed", "completed", "success", "error")
        for task in st.session_state.video_task_queue
    )
    if pending_tasks_exist:
        st_autorefresh(interval=poll_interval * 1000, key="video_poll_refresh")

    # ===== Update Task Status =====
    for task in st.session_state.video_task_queue:
        if task["status"] not in ("succeeded", "failed", "completed", "success", "error"):
            try:
                task_info = get_video_task(api_key, task["task_id"])
                with video_status_box:
                    st.json(task_info)

                status = (task_info.get("status") or "").lower()
                task["status"] = status
                if status in ("succeeded","completed","success"):
                    video_url = find_video_url(task_info)
                    if video_url:
                        task["video_url"] = video_url
                elif status in ("failed","error"):
                    task["video_url"] = None
            except Exception as e:
                task["status"] = f"error (polling failed: {e})"

    # ===== Render Task Status =====
    for task in reversed(st.session_state.video_task_queue):
        with video_status_box.expander(f"Task: {task['task_id']} ({task['status']})", expanded=True):
            st.markdown(f"**Prompt:** {task['prompt']}")
            st.markdown(f"**Mode:** {task['mode']}")
            if task["image_url"]:
                st.markdown("**Input Image:**")
                st.image(task["image_url"], width=200)

            if task["status"] in ("succeeded","completed","success") and task["video_url"]:
                st.video(task["video_url"], format="video/mp4", start_time=0)
                st.markdown(f"[Download video]({task['video_url']})")
            elif task["status"] in ("failed", "error"):
                st.error("Task failed or encountered an error during polling.")
            else:
                st.progress(50, text=f"Processing... Status: {task['status']}")
