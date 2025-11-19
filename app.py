#!/usr/bin/env python3
import subprocess
import sys
import os
import re
import json
import threading
import queue
import time
import shutil
from urllib.parse import quote, unquote
from flask import Flask, render_template_string, request, send_from_directory, flash, url_for, Response, redirect, session, jsonify
from werkzeug.utils import secure_filename
import requests
import yt_dlp

# -----------------------------
# Configuration
# -----------------------------
FLASK_PORT = int(os.environ.get("PORT", 5000))
DOWNLOAD_FOLDER = os.path.join('/tmp', 'downloads')
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

COOKIES_FILE = os.path.join('/tmp', 'youtube_cookies.txt')
# Get cookie content from environment variable and write to /tmp
cookie_content = os.environ.get('YOUTUBE_COOKIES_CONTENT')
if cookie_content:
    with open(COOKIES_FILE, 'w') as f:
        f.write(cookie_content)
        
PIXELDRAIN_API_KEY = os.environ.get("PIXELDRAIN_API_KEY", "")  # optional

print(f"Downloads folder: {os.path.abspath(DOWNLOAD_FOLDER)}")
print(f"Cookies file: {'Exists' if os.path.exists(COOKIES_FILE) else 'Not found'}")

# -----------------------------
# Flask & SSE Setup
# -----------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "a_very_secret_key_for_flask")
progress_queue = queue.Queue()

# -----------------------------
# Main HTML Template (with Manual Merge + Pixeldrain checkbox)
# -----------------------------
TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Video Downloader</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; background-color: #f4f4f9; color: #333; margin: 0; padding: 20px; }
        .container { max-width: 800px; margin: auto; background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        h1, h2, h3 { color: #444; }
        hr { border: 0; border-top: 1px solid #ddd; margin: 20px 0; }
        input[type="text"], input[type="number"], select { width: 100%; padding: 8px; margin: 5px 0 15px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }
        input[type="file"] { margin-bottom: 15px; }
        button { background-color: #007bff; color: white; padding: 10px 15px; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; margin-right: 5px; }
        button:hover { background-color: #0056b3; }
        button.delete { background-color: #dc3545; }
        button.delete:hover { background-color: #c82333; }
        button.upload { background-color: #17a2b8; }
        button.upload:hover { background-color: #138496; }
        button.encode { background-color: #28a745; }
        button.encode:hover { background-color: #218838; }
        button.rename { background-color: #ffc107; color: #212529; }
        button.rename:hover { background-color: #e0a800; }
        a { color: #007bff; text-decoration: none; }
        a:hover { text-decoration: underline; }
        pre { background-color: #eee; padding: 10px; border-radius: 4px; white-space: pre-wrap; word-wrap: break-word; }
        .flash-msg { padding: 10px; border-radius: 4px; margin-bottom: 15px; }
        .flash-success { background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .flash-error { background-color: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        .flash-info { background-color: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }
        .progress-container { display: none; margin-top: 20px; }
        .progress-bar { width: 100%; background-color: #e9ecef; border-radius: 4px; }
        .progress-bar-inner { width: 0%; height: 24px; background-color: #28a745; text-align: center; line-height: 24px; color: white; border-radius: 4px; transition: width 0.4s ease; }
        #progress-log { margin-top: 10px; font-family: monospace; font-size: 12px; max-height: 200px; overflow-y: auto; background: #333; color: #fff; padding: 10px; border-radius: 4px; }
        .notification { position: fixed; top: 20px; right: 20px; padding: 15px 20px; border-radius: 8px; color: white; font-weight: bold; z-index: 10000; animation: slideIn 0.3s ease-out; }
        .notification.success { background-color: #28a745; }
        .notification.error { background-color: #dc3545; }
        .notification.info { background-color: #17a2b8; }
        @keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
    </style>
</head>
<body>
<div class="container">
    <h1>Video Downloader & Uploader</h1>
    <p>Powered by yt-dlp, FFmpeg & Pixeldrain</p>
    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for category, message in messages %}
                <div class="flash-msg flash-{{ category }}">{{ message|safe }}</div>
            {% endfor %}
        {% endif %}
    {% endwith %}

    <div id="progress-container" class="progress-container">
        <h3 id="progress-stage">Starting...</h3>
        <div class="progress-bar">
            <div id="progress-bar-inner" class="progress-bar-inner">0%</div>
        </div>
        <pre id="progress-log"></pre>
    </div>

    <!-- MANUAL MERGE SECTION -->
    <hr>
    <h2>Manual Format Merge</h2>
    <p>Fetch formats from a URL, then manually provide the Video and Audio IDs to merge into an MKV file.</p>
    <form method="POST" action="{{ url_for('index') }}">
        <label>Page URL:</label><br>
        <input type="text" name="manual_url" size="80" value="{{ manual_url }}" required><br>
        <button type="submit" name="action" value="manual_fetch">Fetch Formats</button><br><br>

        {% if manual_formats_raw %}
            <input type="hidden" name="manual_url" value="{{ manual_url }}">
            <h3>Available Formats (Raw):</h3>
            <pre>{{ manual_formats_raw }}</pre>

            <label>Video ID:</label><br>
            <input type="text" name="manual_video_id" required placeholder="Enter the ID of the video stream"><br>

            <label>Audio ID (optional):</label><br>
            <input type="text" name="manual_audio_id" placeholder="Enter ID of audio stream (leave blank for video-only)"><br>
            
            <label>Filename (will be saved as .mkv):</label><br>
            <input type="text" name="manual_filename" value="{{ manual_filename }}" required><br><br>
            
            <label><input type="checkbox" name="upload_pixeldrain_manual" value="true"> Upload to Pixeldrain after merge completes</label><br><br>
            
            <button type="submit" name="action" value="manual_merge">Merge & Download</button>
        {% endif %}
    </form>
    <hr>

    <!-- Rest of your original template (unchanged) -->
    <h2>Advanced Download</h2>
    <form method="POST" action="{{ url_for('index') }}" id="download-form" onsubmit="return validateForm()">
        <label>Video URL:</label><br>
        <input type="text" name="url" size="80" value="{{ url }}" required><br>
        <button type="submit" name="action" value="fetch">Fetch Formats</button><br><br>

        {% if formats %}
            <input type="hidden" name="url" value="{{ url }}">
            
            <label>Video Format:</label><br>
            <select name="video_id" required>
                {% for format in video_formats %}
                    <option value="{{ format.id }}" {% if format.is_muxed %}style="font-style: italic;"{% endif %}>{{ format.display }}{% if format.is_muxed %} (with audio){% endif %}</option>
                {% endfor %}
            </select><br>

            <label>Audio Format (optional):</label><br>
            <select name="audio_id">
                <option value="">Best Audio (default)</option>
                {% for format in audio_formats %}
                    <option value="{{ format.id }}">{{ format.display }}</option>
                {% endfor %}
            </select><br>
            
            <label>Filename:</label><br>
            <input type="text" name="filename" value="{{ original_name }}" required><br>
            <label>Codec:</label><br>
            <select name="codec" id="codec" required>
                <option value="none" {% if codec == "none" %}selected{% endif %}>No Encoding</option>
                <option value="h265" {% if codec == "h265" %}selected{% endif %}>Encode to H.265 (x265)</option>
                <option value="av1" {% if codec == "av1" %}selected{% endif %}>Encode to AV1 (SVT-AV1)</option>
            </select><br>
            <div id="encoding-options" style="display: {% if codec != 'none' %}block{% else %}none{% endif %};">
                <label>Encoding Mode:</label><br>
                <select name="pass_mode" id="pass_mode" required>
                    <option value="1-pass" {% if pass_mode == "1-pass" %}selected{% endif %}>1-pass (CRF)</option>
                    <option value="2-pass" {% if pass_mode == "2-pass" %}selected{% endif %}>2-pass (VBR)</option>
                </select><br>
                <label>Preset (slower = better quality/smaller file):</label><br>
                <select name="preset" id="preset"></select><br>

                <label>Video Bitrate (kb/s, optional):</label><br>
                <input type="number" name="bitrate" id="bitrate" value="{{ bitrate }}" min="100" placeholder="e.g., 2000 for 2 Mbps (leave empty for default)"><br>

                <label>CRF (0–63, lower = better quality):</label><br>
                <input type="number" name="crf" id="crf" value="{{ crf|default(28 if codec == 'h265' else 35) }}" min="0" max="63" step="1" placeholder="e.g., 28 for H.265, 35 for AV1"><br>

                <label>Audio Bitrate (kb/s):</label><br>
                <input type="number" name="audio_bitrate" id="audio_bitrate" value="{{ audio_bitrate|default('96') }}" min="32" max="512" step="8" placeholder="e.g., 64, 96, 128"><br>

                <label>Frame Rate (optional):</label><br>
                <select name="fps">
                    <option value="">Original</option>
                    <option value="24">24 fps</option>
                    <option value="30">30 fps</option>
                    <option value="60">60 fps</option>
                </select><br>

                <label><input type="checkbox" name="force_stereo" value="true"> Force Stereo (2-channel) Audio</label><br>
            </div>
            <script>
                const codecSelect = document.getElementById('codec');
                const presetSelect = document.getElementById('preset');
                const crfInput = document.getElementById('crf');
                const passModeSelect = document.getElementById('pass_mode');
                const bitrateInput = document.getElementById('bitrate');

                function updatePresetOptions() {
                    const codec = codecSelect.value;
                    presetSelect.innerHTML = '';
                    if (codec === 'av1') {
                        for (let p = 0; p <= 13; p++) {
                            let label = p.toString();
                            if (p === 0) label += ' (slowest)';
                            else if (p === 13) label += ' (fastest)';
                            else if (p > 7) label += ' (fast)';
                            else label += ' (medium)';
                            const option = document.createElement('option');
                            option.value = p;
                            option.text = label;
                            if (p === 6) option.selected = true;
                            presetSelect.appendChild(option);
                        }
                        crfInput.value = crfInput.value || '35';
                        crfInput.placeholder = 'e.g., 35 for AV1';
                    } else if (codec === 'h265') {
                        const presets = ['ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', 'veryslow', 'placebo'];
                        presets.forEach(p => {
                            const option = document.createElement('option');
                            option.value = p;
                            option.text = p;
                            if (p === 'faster') option.selected = true;
                            presetSelect.appendChild(option);
                        });
                        crfInput.value = crfInput.value || '28';
                        crfInput.placeholder = 'e.g., 28 for H.265';
                    }
                    const encodingOptions = document.getElementById('encoding-options');
                    encodingOptions.style.display = codec !== 'none' ? 'block' : 'none';
                    
                    if (codec === 'none') {
                        bitrateInput.removeAttribute('required');
                        bitrateInput.removeAttribute('min');
                        bitrateInput.value = '';
                    } else {
                        bitrateInput.setAttribute('min', '100');
                        if (passModeSelect.value === '2-pass') {
                            bitrateInput.setAttribute('required', 'required');
                        } else {
                            bitrateInput.removeAttribute('required');
                        }
                    }
                }

                function validateForm() {
                    const codec = codecSelect.value;
                    if (codec !== 'none') {
                        if (!presetSelect.value) {
                            alert('Please select a preset.');
                            return false;
                        }
                        if (passModeSelect.value === '2-pass' && (!bitrateInput.value || parseInt(bitrateInput.value) < 100)) {
                            alert('Please specify a valid video bitrate (minimum 100) for 2-pass encoding.');
                            return false;
                        }
                    }
                    return true;
                }

                codecSelect.addEventListener('change', updatePresetOptions);
                passModeSelect.addEventListener('change', function() {
                    if (codecSelect.value !== 'none') {
                        if (this.value === '2-pass') {
                            bitrateInput.setAttribute('required', 'required');
                        } else {
                            bitrateInput.removeAttribute('required');
                        }
                    }
                });

                document.addEventListener('DOMContentLoaded', updatePresetOptions);
            </script>
            <br>
            <label><input type="checkbox" name="upload_pixeldrain" value="true"> Upload to Pixeldrain after completion</label><br><br>
            <button type="submit" name="action" value="download">Download & Convert</button>
            <h3>Available Formats (Raw):</h3>
            <pre>{{ formats }}</pre>
        {% endif %}
    </form>
    
    <hr>
    
    <h2>Direct URL Download</h2>
    <form method="POST" action="{{ url_for('index') }}">
        <label>URL (Video, Playlist, or any direct file):</label><br>
        <input type="text" name="direct_url" size="80" required><br>
        <label><input type="checkbox" name="upload_pixeldrain_direct" value="true"> Upload to Pixeldrain after download</label><br>
        <button type="submit" name="action" value="direct_download">Download to Server</button>
        <button type="submit" name="action" value="direct_upload_pixeldrain" class="upload">Upload to Pixeldrain</button>
    </form>

    <hr>

    <h2>Upload File</h2>
    <form method="POST" action="{{ url_for('upload_direct') }}" enctype="multipart/form-data">
        <label>Select a file from your computer to upload to Pixeldrain (or to server):</label><br>
        <input type="file" name="file" required><br>
        <button type="submit" class="upload">Upload to Pixeldrain</button>
    </form>

    <hr>
    <p><a href="{{ url_for('list_files') }}">Manage Downloaded Files</a></p>
</div>

<script>
    function showNotification(message, type = 'info') {
        const notification = document.createElement('div');
        notification.className = `notification ${type}`;
        notification.textContent = message;
        document.body.appendChild(notification);
        
        setTimeout(() => {
            notification.style.opacity = '0';
            setTimeout(() => {
                document.body.removeChild(notification);
            }, 300);
        }, 3000);
    }

    document.addEventListener("DOMContentLoaded", function() {
        {% if download_started %}
            const progressContainer = document.getElementById('progress-container');
            const stage = document.getElementById('progress-stage');
            const progressBar = document.getElementById('progress-bar-inner');
            const log = document.getElementById('progress-log');
            
            progressContainer.style.display = 'block';

            const eventSource = new EventSource("{{ url_for('progress_stream') }}");
            let finalUrl = null;
            
            eventSource.onmessage = function(event) {
                try {
                    const data = JSON.parse(event.data);
                    
                    if (data.final_url) {
                        finalUrl = data.final_url;
                    }
                    
                    if (data.log && data.log === 'DONE') {
                        eventSource.close();
                        stage.textContent = 'Completed!';
                        progressBar.style.backgroundColor = '#28a745';
                        log.innerHTML += "\\n\\nOperation finished. Redirecting...";
                        
                        let redirectTarget = "{{ url_for('list_files') }}";
                        if (finalUrl) {
                            redirectTarget = "{{ url_for('operation_complete') }}?url=" + encodeURIComponent(finalUrl);
                        }
                        
                        setTimeout(() => { window.location.href = redirectTarget; }, 2000);
                        return;
                    }

                    if (data.error) {
                        eventSource.close();
                        stage.textContent = 'Error!';
                        progressBar.style.backgroundColor = '#dc3545';
                        log.innerHTML += `\\n\\nERROR: ${data.error}`;
                        showNotification('Operation failed: ' + data.error, 'error');
                        return;
                    }

                    if (data.stage) {
                        stage.textContent = data.stage;
                    }
                    if (data.percent) {
                        progressBar.style.width = data.percent + '%';
                        progressBar.textContent = data.percent.toFixed(1) + '%';
                    }
                    if (data.log) {
                        log.innerHTML += data.log + '\\n';
                        log.scrollTop = log.scrollHeight;
                    }
                } catch (e) {
                    console.error('Error parsing SSE data:', e);
                }
            };

            eventSource.onerror = function(err) {
                stage.textContent = 'Connection error. Please refresh.';
                eventSource.close();
                console.error('SSE error:', err);
            };
        {% endif %}
    });
</script>
</body>
</html>
"""

# (ENCODE_TEMPLATE and FILE_OPERATION_TEMPLATE remain unchanged - same as your original)
ENCODE_TEMPLATE = """... (your full ENCODE_TEMPLATE here - unchanged) ..."""
FILE_OPERATION_TEMPLATE = """... (your full FILE_OPERATION_TEMPLATE here - unchanged) ..."""

# [Keep all your helper functions exactly as they were]
# ... (all functions from human_size() to get_media_duration() unchanged)

# -----------------------------
# UPDATED: manual_merge_worker with Pixeldrain upload support
# -----------------------------
def manual_merge_worker(url, video_id, audio_id, filename, q, upload_pixeldrain=False):
    """Worker to download and merge streams using manually provided IDs."""
    safe_name = get_safe_filename(filename)
    if not safe_name.lower().endswith('.mkv'):
        safe_name += ".mkv"
    final_path = os.path.join(DOWNLOAD_FOLDER, safe_name)
    try:
        while not q.empty(): q.get()
        q.put({"stage": "Initializing manual download & merge...", "percent": 0})

        video_id_clean = video_id.strip()
        audio_id_clean = audio_id.strip() if audio_id else ""
        format_selector = f"{video_id_clean}+{audio_id_clean}" if audio_id_clean else video_id_clean

        yt_dlp_cmd = [
            sys.executable, "-m", "yt_dlp",
            "-f", format_selector,
            "-o", final_path,
            "--merge-output-format", "mkv",
            url
        ]
        if os.path.exists(COOKIES_FILE):
            yt_dlp_cmd.extend(["--cookies", COOKIES_FILE])

        run_command_with_progress(yt_dlp_cmd, "Downloading & Merging selected formats...", q)
        q.put({"stage": "Merge & Download Complete!", "percent": 100})

        if upload_pixeldrain:
            upload_to_pixeldrain(final_path, os.path.basename(final_path), q)

    except Exception as e:
        q.put({"error": str(e)})
    finally:
        q.put({"log": "DONE"})

# [All other functions remain exactly the same]

# -----------------------------
# Flask Routes - UPDATED manual_merge handling
# -----------------------------
@app.route("/", methods=["POST"])
def index_post():
    action = request.form.get("action")
    form_data = {
        "url": request.form.get("url", "").strip(),
        "manual_url": request.form.get("manual_url", "").strip(),
        "manual_formats_raw": None,
        "manual_filename": "",
        "download_started": False
    }

    if action == "fetch":
        # ... unchanged ...
        pass
    
    elif action == "manual_fetch":
        # ... unchanged ...
        pass
    
    if action in ["download", "direct_download", "direct_upload_pixeldrain", "manual_merge"]:
        form_data["download_started"] = True
        thread_target, thread_args, thread_kwargs = None, (), {}

        if action == "download":
            # ... unchanged ...
            pass
        
        elif action == "manual_merge":
            upload_manual = request.form.get("upload_pixeldrain_manual") == "true"
            thread_target = manual_merge_worker
            thread_args = (
                request.form.get("manual_url"),
                request.form.get("manual_video_id"),
                request.form.get("manual_audio_id"),
                request.form.get("manual_filename"),
                progress_queue,
                upload_manual
            )
        
        elif action in ["direct_download", "direct_upload_pixeldrain"]:
            # ... unchanged ...
            pass

        if thread_target:
            task_thread = threading.Thread(target=thread_target, args=thread_args, kwargs=thread_kwargs)
            task_thread.daemon = True
            task_thread.start()
            
    return render_template_string(TEMPLATE, **form_data)

# [All other routes remain exactly the same]

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=FLASK_PORT)
