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
cookie_content = os.environ.get('YOUTUBE_COOKIES_CONTENT')
if cookie_content:
    with open(COOKIES_FILE, 'w') as f:
        f.write(cookie_content)
        
PIXELDRAIN_API_KEY = os.environ.get("PIXELDRAIN_API_KEY", "")

print(f"📂 Downloads folder: {os.path.abspath(DOWNLOAD_FOLDER)}")
print(f"🍪 Cookies: {'Loaded' if os.path.exists(COOKIES_FILE) else 'Not found'}")

# -----------------------------
# Flask & SSE Setup
# -----------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "super_secret_key_2025")
progress_queue = queue.Queue()

# -----------------------------
# Templates (main + encode + operation)
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
    <p><a href="{{ url_for('list_files') }}">📂 Manage Downloaded Files</a></p>
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
            let finalUrl = null; // Variable to store the final URL from the upload
            
            eventSource.onmessage = function(event) {
                try {
                    const data = JSON.parse(event.data);
                    
                    if (data.final_url) {
                        finalUrl = data.final_url;
                    }
                    
                    if (data.log && data.log === 'DONE') {
                        eventSource.close();
                        stage.textContent = '✅ Completed!';
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
                        stage.textContent = '❌ Error!';
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

ENCODE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Encode Video</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; background-color: #f4f4f9; color: #333; margin: 0; padding: 20px; }
        .container { max-width: 800px; margin: auto; background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        h1, h2, h3 { color: #444; }
        hr { border: 0; border-top: 1px solid #ddd; margin: 20px 0; }
        input[type="text"], input[type="number"], select { width: 100%; padding: 8px; margin: 5px 0 15px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }
        button { background-color: #007bff; color: white; padding: 10px 15px; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; }
        button:hover { background-color: #0056b3; }
        a { color: #007bff; text-decoration: none; }
        a:hover { text-decoration: underline; }
        .flash-msg { padding: 10px; border-radius: 4px; margin-bottom: 15px; }
        .flash-success { background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .flash-error { background-color: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        .progress-container { display: none; margin-top: 20px; }
        .progress-bar { width: 100%; background-color: #e9ecef; border-radius: 4px; }
        .progress-bar-inner { width: 0%; height: 24px; background-color: #28a745; text-align: center; line-height: 24px; color: white; border-radius: 4px; transition: width 0.4s ease; }
        #progress-log { margin-top: 10px; font-family: monospace; font-size: 12px; max-height: 200px; overflow-y: auto; background: #333; color: #fff; padding: 10px; border-radius: 4px; }
    </style>
</head>
<body>
<div class="container">
    <h1>Encode Video: {{ filepath }}</h1>
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

    <form method="POST" onsubmit="return validateEncodeForm()">
        <label>Output Filename (relative to downloads folder):</label><br>
        <input type="text" name="output_filename" value="{{ suggested_output }}" required><br>
        
        <label>Codec:</label><br>
        <select name="codec" id="codec" required>
            <option value="none" {% if codec == "none" %}selected{% endif %}>No Encoding (Copy)</option>
            <option value="h265" {% if codec == "h265" %}selected{% endif %}>Encode to H.265 (x265)</option>
            <option value="av1" {% if codec == "av1" %}selected{% endif %}>Encode to AV1 (SVT-AV1)</option>
        </select><br>
        
        <div id="encoding-options" style="display: {% if codec != 'none' %}block{% else %}none{% endif %};">
            <label>Encoding Mode:</label><br>
            <select name="pass_mode" id="pass_mode">
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

            function validateEncodeForm() {
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
        <button type="submit">Start Encoding</button>
        <a href="{{ url_for('list_files') }}">Back to Files</a>
    </form>
</div>

<script>
    document.addEventListener("DOMContentLoaded", function() {
        {% if download_started %}
            const progressContainer = document.getElementById('progress-container');
            const stage = document.getElementById('progress-stage');
            const progressBar = document.getElementById('progress-bar-inner');
            const log = document.getElementById('progress-log');
            
            progressContainer.style.display = 'block';

            const eventSource = new EventSource("{{ url_for('progress_stream') }}");
            let finalUrl = null; // Variable to store the final URL
            
            eventSource.onmessage = function(event) {
                try {
                    const data = JSON.parse(event.data);
                    
                    if (data.final_url) {
                        finalUrl = data.final_url;
                    }

                    if (data.log && data.log === 'DONE') {
                        eventSource.close();
                        stage.textContent = '✅ Completed!';
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
                        stage.textContent = '❌ Error!';
                        progressBar.style.backgroundColor = '#dc3545';
                        log.innerHTML += `\\n\\nERROR: ${data.error}`;
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

FILE_OPERATION_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Processing...</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; background-color: #f4f4f9; color: #333; margin: 0; padding: 20px; }
        .container { max-width: 800px; margin: auto; background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        h1, h2, h3 { color: #444; }
        pre { background-color: #eee; padding: 10px; border-radius: 4px; white-space: pre-wrap; word-wrap: break-word; }
        .progress-container { display: block; margin-top: 20px; }
        .progress-bar { width: 100%; background-color: #e9ecef; border-radius: 4px; }
        .progress-bar-inner { width: 0%; height: 24px; background-color: #17a2b8; text-align: center; line-height: 24px; color: white; border-radius: 4px; transition: width 0.4s ease; }
        #progress-log { margin-top: 10px; font-family: monospace; font-size: 12px; max-height: 200px; overflow-y: auto; background: #333; color: #fff; padding: 10px; border-radius: 4px; }
    </style>
</head>
<body>
<div class="container">
    <h1>{{ operation_title }}</h1>
    <p>Please wait while the operation completes. You will be redirected automatically.</p>
    <div id="progress-container" class="progress-container">
        <h3 id="progress-stage">Starting...</h3>
        <div class="progress-bar">
            <div id="progress-bar-inner" class="progress-bar-inner" style="background-color: #17a2b8;">0%</div>
        </div>
        <pre id="progress-log"></pre>
    </div>
</div>

<script>
    document.addEventListener("DOMContentLoaded", function() {
        {% if download_started %}
            const stage = document.getElementById('progress-stage');
            const progressBar = document.getElementById('progress-bar-inner');
            const log = document.getElementById('progress-log');
            
            const eventSource = new EventSource("{{ url_for('progress_stream') }}");
            let finalUrl = null;
            
            eventSource.onmessage = function(event) {
                try {
                    const data = JSON.parse(event.data);
                    if (data.final_url) finalUrl = data.final_url;
                    if (data.log && data.log === 'DONE') {
                        eventSource.close();
                        stage.textContent = '✅ Completed!';
                        progressBar.style.backgroundColor = '#28a745';
                        log.innerHTML += "\\n\\nOperation finished. Redirecting...";
                        let redirectTarget = "{{ url_for('list_files') }}";
                        if (finalUrl) redirectTarget = "{{ url_for('operation_complete') }}?url=" + encodeURIComponent(finalUrl);
                        setTimeout(() => { window.location.href = redirectTarget; }, 2000);
                        return;
                    }
                    if (data.error) {
                        eventSource.close();
                        stage.textContent = '❌ Error!';
                        progressBar.style.backgroundColor = '#dc3545';
                        log.innerHTML += `\\n\\nERROR: ${data.error}`;
                        return;
                    }
                    if (data.stage) stage.textContent = data.stage;
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

# -----------------------------
# Helper Functions
# -----------------------------
def human_size(size_bytes):
    if size_bytes is None or size_bytes == 0:
        return "0 B"
    power = 1024
    n = 0
    power_labels = {0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size_bytes >= power and n < len(power_labels) -1 :
        size_bytes /= power
        n += 1
    return f"{size_bytes:.1f} {power_labels[n]}iB"

def get_safe_filename(name):
    """Sanitizes a string to be a valid filename component, allowing slashes for paths."""
    parts = name.split('/')
    safe_parts = [re.sub(r'[\\/*?:"<>|]', "_", part) for part in parts]
    safe_parts = [re.sub(r'\s+', ' ', part).strip() for part in safe_parts]
    return '/'.join(safe_parts)

def get_file_size(file_path):
    try:
        return human_size(os.path.getsize(file_path))
    except FileNotFoundError:
        return "N/A"

def is_media_file(file_path):
    video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', '.m4v', '.3gp', '.mpg', '.mpeg', '.ts', '.vob'}
    audio_extensions = {'.mp3', '.wav', '.flac', '.aac', '.ogg', '.wma', '.m4a', '.opus'}
    ext = os.path.splitext(os.path.basename(file_path))[1].lower()
    return ext in video_extensions or ext in audio_extensions

def get_media_info(file_path):
    try:
        command = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", "-show_format", file_path
        ]
        result = subprocess.check_output(command, stderr=subprocess.STDOUT)
        data = json.loads(result)
        info = {}
        video_stream = next((s for s in data.get('streams', []) if s.get('codec_type') == 'video'), None)
        audio_stream = next((s for s in data.get('streams', []) if s.get('codec_type') == 'audio'), None)
        if video_stream:
            info['video_codec'] = video_stream.get('codec_name', 'N/A')
            fr_str = video_stream.get('avg_frame_rate', '0/1')
            if '/' in fr_str and fr_str != '0/1':
                num, den = map(int, fr_str.split('/'))
                info['video_fps'] = f"{num / den:.2f}" if den else '0.00'
            else:
                info['video_fps'] = 'N/A'
            v_br = video_stream.get('bit_rate')
            if not v_br and 'format' in data: v_br = data['format'].get('bit_rate')
            info['video_bitrate'] = f"{int(v_br) // 1000} kbps" if v_br else 'N/A'
        if audio_stream:
            info['audio_codec'] = audio_stream.get('codec_name', 'N/A')
            a_br = audio_stream.get('bit_rate')
            info['audio_bitrate'] = f"{int(a_br) // 1000} kbps" if a_br else 'N/A'
        return info
    except Exception as e:
        return {"error": "Could not retrieve media information."}

def fetch_formats(url):
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'skip_download': True,
            'format': 'best',
        }
        if os.path.exists(COOKIES_FILE):
            ydl_opts['cookiefile'] = COOKIES_FILE

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = info.get('formats', []) or []
        if not formats and 'entries' in info:
            first = next((e for e in info['entries'] if e), {})
            formats = first.get('formats', []) or []

        video_formats = []
        audio_formats = []
        raw_lines = []

        for f in formats:
            fid = f.get('format_id', 'unknown')
            height = f.get('height') or 0
            fps = f.get('fps') or 0
            acodec = f.get('acodec', 'none')
            vcodec = f.get('vcodec', 'none')
            filesize = f.get('filesize') or f.get('filesize_approx') or 0
            size = human_size(filesize) if filesize else "Unknown"
            abr = f.get('abr', 0)
            vbr = f.get('tbr', 0) or f.get('vbr', 0)

            raw_lines.append(f"{fid}: {vcodec} | {acodec} | {height}p | {fps}fps | {size}")

            is_video_only = vcodec != 'none' and acodec == 'none'
            is_muxed = vcodec != 'none' and acodec != 'none'
            is_audio_only = vcodec == 'none' and acodec != 'none'

            if is_video_only:
                video_formats.append({
                    'id': fid, 'display': f"{height}p {fps}fps {vcodec.upper()} ~{int(vbr)}k ({size})",
                    'h': height, 'fps': fps, 'is_muxed': False
                })
            elif is_muxed:
                video_formats.append({
                    'id': fid, 'display': f"{height}p {fps}fps {vcodec.upper()}+{acodec.upper()} ({size})",
                    'h': height, 'fps': fps, 'is_muxed': True
                })
            elif is_audio_only:
                audio_formats.append({
                    'id': fid, 'display': f"{acodec.upper()} {int(abr)}kbps ({size})",
                    'br': abr
                })

        video_formats.sort(key=lambda x: (x.get('h', 0), x.get('fps', 0)), reverse=True)
        audio_formats.sort(key=lambda x: x.get('br', 0), reverse=True)
        return '\n'.join(raw_lines), video_formats, audio_formats
    except Exception as e:
        error_msg = str(e)
        if "videoModel" in error_msg or "Private video" in error_msg or "unavailable" in error_msg:
            flash("This video may be private, age-restricted, or region-blocked. Try logging in with cookies.", "error")
        else:
            flash(f"Format fetch failed: {error_msg}", "error")
        return "", [], []

def get_original_filename(url):
    try:
        ydl_opts = {'quiet': True}
        if os.path.exists(COOKIES_FILE):
            ydl_opts['cookiefile'] = COOKIES_FILE
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        title = info.get('title', 'download').strip()
        safe_title = re.sub(r'[\\/*?:"<>|]', "_", title)
        return f"{safe_title}.mkv"
    except Exception:
        return "download.mkv"

def run_command_with_progress(command, stage, q):
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, encoding='utf-8', errors='ignore')
    for line in iter(process.stdout.readline, ''):
        q.put({"log": line.strip()})
        match = re.search(r'\[download\]\s+([0-9.]+)%', line)
        if match:
            q.put({"stage": stage, "percent": float(match.group(1))})
    if process.wait() != 0:
        raise subprocess.CalledProcessError(process.returncode, command)

def upload_to_pixeldrain(file_path, filename, q):
    try:
        q.put({"stage": f"Uploading '{filename}' to Pixeldrain...", "percent": 10})
        api_url = "https://pixeldrain.com/api/file"
        with open(file_path, 'rb') as f:
            files = {'file': (filename, f)}
            auth = ('', PIXELDRAIN_API_KEY) if PIXELDRAIN_API_KEY else None
            q.put({"stage": "Sending data...", "percent": 50})
            response = requests.post(api_url, files=files, auth=auth)
        response.raise_for_status()
        result = response.json()
        if result.get("success"):
            file_id = result.get("id")
            pixeldrain_url = f"https://pixeldrain.com/u/{file_id}"
            q.put({"stage": "✅ Pixeldrain Upload Complete!", "percent": 100})
            q.put({"log": f"Success! Link: {pixeldrain_url}", "final_url": pixeldrain_url})
        else:
            q.put({"error": f"Pixeldrain API error: {result.get('message', 'Unknown')}"})
    except Exception as e:
        q.put({"error": f"Pixeldrain upload failed: {str(e)}"})
    finally:
        q.put({"log": "DONE"})

def get_audio_channels(file_path):
    try:
        ffprobe_cmd = ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=channels", "-of", "default=noprint_wrappers=1:nokey=1", file_path]
        channels_str = subprocess.check_output(ffprobe_cmd, universal_newlines=True, stderr=subprocess.DEVNULL).strip()
        return int(channels_str) if channels_str else 2
    except Exception:
        return 2

def get_media_duration(file_path):
    try:
        cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", file_path]
        out = subprocess.check_output(cmd, universal_newlines=True, stderr=subprocess.DEVNULL).strip()
        return float(out) if out else 0.0
    except Exception:
        return 0.0

# -----------------------------
# Core operations
# -----------------------------
def encode_file(input_path, output_filename, codec, preset, pass_mode, bitrate, crf, audio_bitrate, fps, force_stereo, q, upload_pixeldrain=False):
    safe_output = get_safe_filename(output_filename)
    output_path = os.path.join(DOWNLOAD_FOLDER, safe_output)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    if os.path.exists(output_path):
        os.remove(output_path)
    try:
        while not q.empty(): q.get()
        q.put({"stage": "Initializing encoding...", "percent": 0})
        if not is_media_file(input_path):
            q.put({"error": "This file type cannot be encoded. Only video and audio files are supported."})
            return
        duration = get_media_duration(input_path)
        
        if codec == "none":
            shutil.copy2(input_path, output_path)
            q.put({"stage": "✅ Copied!", "percent": 100, "log": "File copied without encoding."})
        else:
            video_codec = "libx265" if codec == "h265" else "libsvtav1"
            crf_val = int(crf) if crf else (28 if codec == 'h265' else 35)
            bitrate_val = int(bitrate) if bitrate and bitrate.strip() else 0
            stage_msg = f"Encoding to {codec.upper()}..."
            q.put({"stage": stage_msg, "percent": 0})
            
            ffmpeg_cmd = ["ffmpeg", "-y", "-i", input_path]
            if pass_mode == "2-pass":
                if bitrate_val == 0:
                    q.put({"error": "Video bitrate is required for 2-pass encoding."}); return
                video_opts = ["-c:v", video_codec, "-preset", preset, "-b:v", f"{bitrate_val}k"]
                pass1_cmd = ffmpeg_cmd + video_opts + ["-pass", "1", "-an", "-f", "null", "-"]
                subprocess.run(pass1_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                ffmpeg_cmd.extend(video_opts + ["-pass", "2"])
            else:
                ffmpeg_cmd.extend(["-c:v", video_codec, "-preset", preset, "-crf", str(crf_val)])
            
            if fps: ffmpeg_cmd.extend(["-r", fps])
            audio_bitrate_val = int(audio_bitrate) if audio_bitrate else 96
            ffmpeg_cmd.extend(["-ac", "2" if force_stereo else str(get_audio_channels(input_path)), "-c:a", "libopus", "-b:a", f"{audio_bitrate_val}k"])
            ffmpeg_cmd.append(output_path)
            
            process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, encoding='utf-8', errors='ignore')
            for line in iter(process.stdout.readline, ''):
                q.put({"log": line.strip()})
                if duration > 0:
                    match = re.search(r'time=(\d{2}):(\d{2}):(\d{2})\.(\d{2})', line)
                    if match:
                        h, m, s, ms = map(int, match.groups())
                        percent = min(100, ((h*3600 + m*60 + s + ms/100) / duration) * 100)
                        q.put({"stage": stage_msg, "percent": percent})
            if process.wait() != 0:
                raise subprocess.CalledProcessError(process.returncode, ffmpeg_cmd)
            q.put({"stage": "✅ Encoding Complete!", "percent": 100})

        if upload_pixeldrain:
            upload_to_pixeldrain(output_path, os.path.basename(safe_output), q)
    except Exception as e:
        q.put({"error": str(e)})
    finally:
        q.put({"log": "DONE"})

def download_and_convert(url, video_id, audio_id, filename, codec, preset, pass_mode, bitrate, crf, audio_bitrate, fps, force_stereo, q, is_muxed, **kwargs):
    safe_name = get_safe_filename(filename)
    base_name, _ = os.path.splitext(safe_name)
    final_path = os.path.join(DOWNLOAD_FOLDER, safe_name)
    tmp_path = os.path.join(DOWNLOAD_FOLDER, base_name + ".part.mkv")
    try:
        while not q.empty(): q.get()
        q.put({"stage": "Initializing download.", "percent": 0})
        
        format_selector = video_id
        if not is_muxed and audio_id:
            format_selector += f"+{audio_id}"
        elif not is_muxed: # Video only stream selected, and no audio selected, so pick best audio
            format_selector += "+bestaudio"

        yt_dlp_cmd = [sys.executable, "-m", "yt_dlp", "-f", format_selector, "-o", tmp_path, "--merge-output-format", "mkv", url]
        if os.path.exists(COOKIES_FILE):
            yt_dlp_cmd.extend(["--cookies", COOKIES_FILE])
            
        run_command_with_progress(yt_dlp_cmd, "Downloading with yt-dlp.", q)
        q.put({"stage": "Download Complete", "percent": 100})
        
        if not os.path.exists(tmp_path):
             raise FileNotFoundError("yt-dlp did not create the expected file.")

        if codec == "none":
            if os.path.exists(final_path): os.remove(final_path)
            os.rename(tmp_path, final_path)
            q.put({"stage": "✅ Done!", "log": "File saved without encoding."})
        else:
            final_path = os.path.join(DOWNLOAD_FOLDER, base_name + ".mkv")
            encode_file(tmp_path, os.path.basename(final_path), codec, preset, pass_mode, bitrate, crf, audio_bitrate, fps, force_stereo, q, upload_pixeldrain=kwargs.get("upload_pixeldrain", False))
        
        if kwargs.get("upload_pixeldrain") and codec == "none":
            upload_to_pixeldrain(final_path, os.path.basename(final_path), q)
    except Exception as e:
        q.put({"error": str(e)})
    finally:
        if os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except OSError: pass
        q.put({"log": "DONE"})

def manual_merge_worker(url, video_id, audio_id, filename, q, upload_pixeldrain=False):
    safe_name = get_safe_filename(filename)
    if not safe_name.lower().endswith('.mkv'):
        safe_name += ".mkv"
    final_path = os.path.join(DOWNLOAD_FOLDER, safe_name)

    try:
        while not q.empty(): q.get()
        q.put({"stage": "Preparing manual merge...", "percent": 0})

        selector = video_id.strip()
        if audio_id and audio_id.strip():
            selector += "+" + audio_id.strip()

        cmd = [
            sys.executable, "-m", "yt_dlp",
            "-f", selector,
            "--merge-output-format", "mkv",
            "-o", final_path,
            "--newline",
            url
        ]
        if os.path.exists(COOKIES_FILE):
            cmd += ["--cookies", COOKIES_FILE]

        run_command_with_progress(cmd, "Downloading & merging formats...", q)
        q.put({"stage": "Merge completed!", "percent": 100})

        if upload_pixeldrain and os.path.exists(final_path):
            upload_to_pixeldrain(final_path, os.path.basename(final_path), q)

    except Exception as e:
        q.put({"error": f"Manual merge failed: {str(e)}"})
    finally:
        q.put({"log": "DONE"})

def download_file_directly(url, q, upload_pixeldrain_direct=False):
    try:
        while not q.empty(): q.get()
        q.put({"stage": "Starting direct download.", "percent": 0})
        with requests.get(url, stream=True, allow_redirects=True, headers={'User-Agent': 'Mozilla/5.0'}) as r:
            r.raise_for_status()
            filename = None
            cd_header = r.headers.get('content-disposition')
            if cd_header:
                match_star = re.search(r"filename\\*=([^']*)''([^;]*)", cd_header)
                if match_star:
                    charset = match_star.group(1); encoded_name = match_star.group(2)
                    try: filename = unquote(encoded_name, encoding=charset)
                    except Exception: filename = unquote(encoded_name)
                if not filename:
                    match_simple = re.search(r'filename="?([^"]+)"?', cd_header)
                    if match_simple: raw_name = match_simple.group(1); filename = raw_name
            if not filename:
                filename_from_url = url.split('/')[-1].split('?')[0]
                if filename_from_url: filename = unquote(filename_from_url)
                else: filename = "direct_download"
            safe_name = get_safe_filename(filename)
            final_path = os.path.join(DOWNLOAD_FOLDER, safe_name)
            total_size = int(r.headers.get('content-length', 0))
            downloaded_size = 0
            q.put({"log": f"Identified filename: '{filename}'"})
            q.put({"log": f"Saving as: '{safe_name}'"})
            os.makedirs(os.path.dirname(final_path), exist_ok=True)
            with open(final_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if not chunk: continue
                    f.write(chunk); downloaded_size += len(chunk)
                    if total_size > 0:
                        percent = (downloaded_size / total_size) * 100
                        q.put({"stage": "Downloading...", "percent": percent})
            q.put({"stage": "✅ Saved!", "percent": 100})
            if upload_pixeldrain_direct:
                upload_to_pixeldrain(final_path, os.path.basename(final_path), q)
    except Exception as e:
        q.put({"error": f"Direct download failed: {str(e)}"})
    finally:
        q.put({"log": "DONE"})

# -----------------------------
# Flask routes
# -----------------------------
@app.route("/")
def index():
    template_vars = {
        "url": "", "formats": None, "download_started": False,
        "manual_url": "", "manual_formats_raw": None, "manual_filename": ""
    }
    if 'last_upload_url' in session:
        flash(f"✅ Upload completed! <a href='{session.pop('last_upload_url')}' target='_blank'>View Link</a>", "success")
    return render_template_string(TEMPLATE, **template_vars)

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
        raw, vfmt, afmt = fetch_formats(form_data["url"])
        if raw:
            form_data.update({
                "formats": raw, "video_formats": vfmt,
                "audio_formats": afmt, "original_name": get_original_filename(form_data["url"])
            })
            session['video_formats_for_mux_check'] = vfmt
            flash("Formats loaded successfully!", "success")
        return render_template_string(TEMPLATE, **form_data)
    
    elif action == "manual_fetch":
        raw, _, __ = fetch_formats(form_data["manual_url"])
        if raw:
            form_data["manual_formats_raw"] = raw
            form_data["manual_filename"] = get_original_filename(form_data["manual_url"]).replace('.mkv', '')
            flash("Manual formats loaded!", "success")
        return render_template_string(TEMPLATE, **form_data)
    
    if action in ["download", "direct_download", "direct_upload_pixeldrain", "manual_merge"]:
        form_data["download_started"] = True
        thread = None

        if action == "download":
            video_formats = session.pop('video_formats_for_mux_check', [])
            video_id = request.form.get("video_id")
            is_muxed = any(f['id'] == video_id and f.get('is_muxed') for f in video_formats)
            thread = threading.Thread(
                target=download_and_convert,
                args=(
                    request.form.get("url"), video_id, request.form.get("audio_id"),
                    request.form.get("filename"), request.form.get("codec"), request.form.get("preset"),
                    request.form.get("pass_mode"), request.form.get("bitrate"), request.form.get("crf"),
                    request.form.get("audio_bitrate"), request.form.get("fps"),
                    request.form.get("force_stereo") == "true", progress_queue, is_muxed
                ),
                kwargs={"upload_pixeldrain": request.form.get("upload_pixeldrain") == "true"}
            )
        
        elif action == "manual_merge":
            upload = request.form.get("upload_pixeldrain_manual") == "true"
            thread = threading.Thread(
                target=manual_merge_worker,
                args=(
                    request.form.get("manual_url"), request.form.get("manual_video_id"),
                    request.form.get("manual_audio_id"), request.form.get("manual_filename"),
                    progress_queue, upload
                )
            )
        
        elif action == "direct_download":
            thread = threading.Thread(
                target=download_file_directly,
                args=(
                    request.form.get("direct_url"), progress_queue,
                    request.form.get("upload_pixeldrain_direct") == "true"
                )
            )
        
        elif action == "direct_upload_pixeldrain":
             thread = threading.Thread(target=download_file_directly, args=(request.form.get("direct_url"), progress_queue, True))

        if thread:
            thread.daemon = True
            thread.start()
            
    return render_template_string(TEMPLATE, **form_data)

@app.route("/progress")
def progress_stream():
    def generate():
        while True:
            try:
                msg = progress_queue.get(timeout=30)
                yield f"data: {json.dumps(msg)}\n\n"
                if msg.get("log") == "DONE": break
            except queue.Empty:
                yield ': keep-alive\n\n'
            except GeneratorExit:
                break
    return Response(generate(), mimetype="text/event-stream")

@app.route("/upload_direct", methods=["POST"])
def upload_direct():
    if 'file' in request.files and request.files['file'].filename:
        file = request.files['file']
        filename = secure_filename(file.filename)
        file_path = os.path.join(DOWNLOAD_FOLDER, filename)
        file.save(file_path)
        thread = threading.Thread(target=upload_to_pixeldrain, args=(file_path, filename, progress_queue))
        thread.daemon = True
        thread.start()
        return render_template_string(FILE_OPERATION_TEMPLATE, operation_title=f"Uploading: {filename}", download_started=True)
    flash("No file selected", "error")
    return redirect(url_for('index'))

@app.route("/upload_local", methods=["POST"])
def upload_local():
    if 'file' in request.files and request.files['file'].filename:
        file = request.files['file']
        filename = secure_filename(file.filename)
        file_path = os.path.join(DOWNLOAD_FOLDER, filename)
        try:
            file.save(file_path)
            flash(f"Saved to server: {filename}", "success")
        except Exception as e:
            flash(f"Failed to save file: {e}", "error")
    else:
        flash("No file selected.", "error")
    return redirect(url_for('list_files'))

@app.route("/files")
@app.route("/files/<path:path>")
def list_files(path=""):
    subpath = path.strip("/")
    base = os.path.join(DOWNLOAD_FOLDER, subpath) if subpath else DOWNLOAD_FOLDER
    if not os.path.abspath(base).startswith(os.path.abspath(DOWNLOAD_FOLDER)):
        flash("Invalid path.", "error"); return redirect(url_for('list_files'))

    items = []
    try: entries = os.listdir(base)
    except FileNotFoundError: entries = []

    for name in entries:
        full = os.path.join(base, name)
        rel_path = os.path.join(subpath, name) if subpath else name
        stat = os.stat(full)
        items.append({
            "name": name, "path": rel_path, "display_path": rel_path,
            "is_dir": os.path.isdir(full), "mtime": stat.st_mtime,
            "size": get_file_size(full),
            "is_media": is_media_file(full) if os.path.isfile(full) else False
        })
    items.sort(key=lambda x: (not x["is_dir"], -x["mtime"]))
    parent_path = "/".join(subpath.split("/")[:-1]) if subpath else ""
    parent_url = url_for("list_files", path=parent_path) if subpath else None

    return render_template_string("""
<!DOCTYPE html><html><head><title>Downloaded Files</title><style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;background-color:#f4f4f9;color:#333;margin:20px}
.container{max-width:1000px;margin:auto;background:#fff;padding:20px;border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,0.1)}
table{width:100%;border-collapse:collapse;margin-top:20px} th,td{padding:12px;border-bottom:1px solid #ddd;text-align:left;word-break:break-all}
th{background-color:#f2f2f2} a{color:#007bff;text-decoration:none} a:hover{text-decoration:underline}
.flash-msg{padding:10px;border-radius:4px;margin-bottom:15px} .flash-success{background-color:#d4edda;color:#155724} .flash-error{background-color:#f8d7da;color:#721c24}
button,button-link{background-color:#007bff;color:#fff!important;padding:5px 10px;border:none;border-radius:4px;cursor:pointer;font-size:14px;margin-right:5px;text-decoration:none;display:inline-block}
button:hover,button-link:hover{background-color:#0056b3} button.delete{background-color:#dc3545} button.delete:hover{background-color:#c82333}
button.upload{background-color:#17a2b8} button.upload:hover{background-color:#138496}
button.encode{background-color:#28a745} button.encode:hover{background-color:#218838} button.rename{background-color:#ffc107;color:#212529!important} button.rename:hover{background-color:#e0a800}
.actions{white-space:nowrap} .actions form{display:inline-block}
</style></head><body>
<div class="container">
    <h1>Files in {{ folder_name }}</h1>
    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for category, message in messages %}
                <div class="flash-msg flash-{{ category }}">{{ message|safe }}</div>
            {% endfor %}
        {% endif %}
    {% endwith %}
    {% if parent_url %}<p><a href="{{ parent_url }}">⬆️ Up</a></p>{% endif %}
    <h3>Upload a file from your computer to the server</h3>
    <form method="POST" action="{{ url_for('upload_local') }}" enctype="multipart/form-data" style="margin-bottom:20px;">
        <input type="file" name="file" required>
        <button type="submit" class="upload">Upload to Server</button>
    </form>
    {% if items %}
        <table><thead><tr><th>Name</th><th>Size</th><th>Modified</th><th>Actions</th></tr></thead><tbody>
        {% for item in items %}
        <tr>
            <td>{{ item.display_path }}</td>
            <td>{{ item.size }}</td>
            <td>{{ item.mtime | int | timestamp_to_datetime }}</td>
            <td class="actions">
                {% if item.is_dir %}
                    <a href="{{ url_for('list_files', path=item.path) }}">Open</a>
                {% else %}
                    <a href="{{ url_for('download_file', filepath=item.path) }}">Download</a>
                    <a href="{{ url_for('encode_page', filepath=item.path) }}" class="encode">Encode</a>
                    <form method="POST" action="{{ url_for('delete_file', filepath=item.path) }}" style="display:inline;">
                        <button type="submit" class="delete" onclick="return confirm('Delete \\'{{ item.display_path }}\\'?')">Delete</button>
                    </form>
                {% endif %}
            </td>
        </tr>
        {% endfor %}
        </tbody></table>
    {% else %}
        <p>No files downloaded yet.</p>
    {% endif %}
    <br><a href="{{ url_for('index') }}">🏠 Back to Main Page</a>
</div>
</body></html>
    """, items=items, folder_name=subpath or "/", parent_url=parent_url)

@app.template_filter('timestamp_to_datetime')
def timestamp_to_datetime(s):
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(s))

@app.route("/encode/<path:filepath>")
def encode_page(filepath):
    full_path = os.path.join(DOWNLOAD_FOLDER, filepath)
    if not os.path.exists(full_path):
        flash("File not found.", "error"); return redirect(url_for('list_files'))
    suggested = os.path.basename(filepath)
    return render_template_string(ENCODE_TEMPLATE, filepath=filepath, suggested_output=suggested, codec="none", pass_mode="1-pass", bitrate="", crf="", audio_bitrate="", download_started=False)

@app.route("/encode/<path:filepath>", methods=["POST"])
def encode_file_post(filepath):
    if not os.path.exists(os.path.join(DOWNLOAD_FOLDER, filepath)):
        flash("File not found.", "error"); return redirect(url_for('list_files'))
    output_filename = request.form.get("output_filename") or os.path.basename(filepath)
    thread = threading.Thread(
        target=encode_file,
        args=(
            os.path.join(DOWNLOAD_FOLDER, filepath), output_filename, request.form.get("codec"),
            request.form.get("preset"), request.form.get("pass_mode"), request.form.get("bitrate"),
            request.form.get("crf"), request.form.get("audio_bitrate"), request.form.get("fps"),
            request.form.get("force_stereo") == "true", progress_queue
        ),
        kwargs={"upload_pixeldrain": request.form.get("upload_pixeldrain") == "true"}
    )
    thread.daemon = True
    thread.start()
    return render_template_string(ENCODE_TEMPLATE, filepath=filepath, suggested_output=output_filename, download_started=True)

@app.route("/operation_complete")
def operation_complete():
    if request.args.get('url'): session['last_upload_url'] = request.args.get('url')
    return redirect(url_for('list_files'))

@app.route("/download/<path:filepath>")
def download_file(filepath):
    return send_from_directory(DOWNLOAD_FOLDER, filepath, as_attachment=True)

@app.route("/delete/<path:filepath>", methods=["POST"])
def delete_file(filepath):
    full_path = os.path.join(DOWNLOAD_FOLDER, filepath)
    if not os.path.abspath(full_path).startswith(os.path.abspath(DOWNLOAD_FOLDER)):
        flash("Invalid path specified.", "error")
        return redirect(url_for('list_files'))
    try:
        if os.path.isdir(full_path):
            shutil.rmtree(full_path)
        else:
            os.remove(full_path)
        flash("Deleted successfully.", "success")
    except Exception as e:
        flash(f"Error deleting: {e}", "error")
    return redirect(url_for('list_files'))

# -----------------------------
# Start app
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=FLASK_PORT)
