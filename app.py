import os
import threading
from flask import Flask, request, jsonify, render_template_string, send_from_directory
import re

# --- API ENDPOINTS ---
import telebot
from telebot import types

# --- TELEGRAM SETUP ---
import os
from dotenv import load_dotenv

# Import your agent class from swarm_agent.py
try:
    from swarm_agent import KaggleSwarmAgent
except ImportError:
    print("⚠️ Error: Could not import 'KaggleSwarmAgent' from swarm_agent.py.")
    exit(1)

app = Flask(__name__)

# Dictionary to store running agents: {"comp_name": KaggleSwarmAgent_instance}
active_jobs = {}

# --- HTML FRONTEND ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Kaggle Swarm Control</title>
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <style>
        body { font-family: Arial; display: flex; height: 100vh; margin: 0; background: #1e1e1e; color: #fff; overflow: hidden; }

        /* Sidebar styling - locked width to prevent collapsing */
        #sidebar { min-width: 320px; width: 320px; flex-shrink: 0; background: #2d2d2d; padding: 20px; border-right: 1px solid #444; overflow-y: auto;}

        /* Main log area styling */
        #main { flex-grow: 1; display: flex; flex-direction: column; padding: 20px; height: 100vh; box-sizing: border-box; overflow: hidden; }

        .box { background: #333; padding: 15px; border-radius: 8px; margin-bottom: 20px; flex-shrink: 0;}
        input, button { padding: 10px; margin-top: 5px; width: 100%; box-sizing: border-box; }
        button { background: #007acc; color: white; border: none; cursor: pointer; border-radius: 4px; transition: 0.2s;}
        button:hover { background: #005f9e; }

        #logs { flex-grow: 1; background: #0d0d0d; color: #1abc9c; padding: 20px; overflow-y: auto; font-family: 'Consolas', monospace; border-radius: 8px; line-height: 1.5;}

        /* Job Button Dynamic States */
        .job-btn { background: #444; margin-bottom: 8px; text-align: left; border-left: 5px solid transparent; }
        .active-job { background: #555; font-weight: bold; }
        .state-thinking { border-left-color: #f39c12 !important; } 
        .state-executing { border-left-color: #3498db !important; } 
        .state-waiting { border-left-color: #2ecc71 !important; } 
        .state-error { border-left-color: #e74c3c !important; } 
        .state-fetching { border-left-color: #9b59b6 !important; } 

        /* File Links */
        .file-link { color: #3498db; text-decoration: none; cursor: pointer; display: block; margin: 8px 0; font-size: 0.95em; padding: 5px; background: #222; border-radius: 4px;}
        .file-link:hover { background: #333; }

        /* Beautiful Markdown Tables */
        #logs table { border-collapse: collapse; width: 100%; margin: 15px 0; color: #fff; background-color: #1e1e1e; }
        #logs th, #logs td { border: 1px solid #444; padding: 10px; text-align: left; }
        #logs th { background-color: #2d2d2d; color: #3498db; font-weight: bold; }
        #logs tr:nth-child(even) { background-color: #252525; }
        #logs h1, #logs h2, #logs h3 { color: #fff; margin-top: 20px; border-bottom: 1px solid #333; padding-bottom: 5px; }
        #logs p { margin: 10px 0; }
        #logs strong { color: #f39c12; }

        /* Slide-over File Viewer */
        #file_viewer {
            position: fixed; right: -50%; top: 0; width: 50%; height: 100vh;
            background: #1a1a1a; border-left: 2px solid #444; padding: 30px;
            box-shadow: -10px 0 30px rgba(0,0,0,0.8); transition: 0.4s ease-in-out; 
            overflow-y: hidden; z-index: 1000; box-sizing: border-box; display: flex; flex-direction: column;
        }
        #file_viewer.open { right: 0; }
        .close-btn { color: #ff5f56; cursor: pointer; float: right; font-size: 1.2em; font-weight: bold; padding: 5px; }
        .close-btn:hover { color: #ff2a1f; }
        #file_content { white-space: pre-wrap; font-family: 'Consolas', monospace; color: #ddd; margin-top: 20px; font-size: 0.9em; word-wrap: break-word; overflow-y: auto; flex-grow: 1;}
        #file_iframe { width: 100%; flex-grow: 1; border: none; background: white; border-radius: 4px; margin-top: 20px; display: none; }
    </style>
</head>
<body>
    <div id="sidebar">
        <h2>🚀 New Job</h2>
        <div class="box">
            <input type="text" id="comp_name" placeholder="Competition Name or URL (e.g. titanic or https://...)" style="margin-bottom: 5px;">
            <input type="number" id="start_iterations" placeholder="Iterations" value="5" min="1" style="margin-bottom: 5px;">
            <button onclick="startJob()">Start Swarm</button>
        </div>

        <h2>Active Jobs</h2>
        <div id="job_list"></div>

        <h2 id="files_title" style="display:none; margin-top: 30px;">📂 Main Files</h2>
        <div id="file_list"></div>
    </div>

    <div id="main">
        <h2 id="current_job_title">Select a Job</h2>
        <div style="display: flex; align-items: center; gap: 15px; margin-bottom: 10px;">
            <h4 id="current_job_status" style="color: #aaa; margin: 0;">Status: Idle</h4>

            <span id="token_counts" style="color: #aaa; font-size: 0.85em; background: #222; padding: 4px 10px; border-radius: 6px; border: 1px solid #444; display: none;">
                Tokens 
                <span style="color: #f39c12; margin-left: 5px;">In: <span id="tokens_in">0</span></span> | 
                <span style="color: #3498db;">Out: <span id="tokens_out">0</span></span> |
                <span style="color: #2ecc71; margin-left: 5px; font-weight: bold;">Cost: $<span id="total_cost">0.0000</span></span>
            </span>
        </div>

        <div id="logs"></div>


        <div class="box" style="margin-top: 20px; display: flex; gap: 10px; flex-wrap: wrap;">
            <input type="text" id="feedback_msg" placeholder="Tell the agent what to do next or ask a question..." style="flex-grow: 1; min-width: 250px;">
            <input type="number" id="run_iterations" placeholder="Iter" value="5" min="1" style="width: 70px;">
            <button onclick="sendFeedback('resume')" style="width: auto;">Run/Resume</button>
            <button onclick="sendFeedback('ask')" style="width: auto; background: #9b59b6;">Ask Question</button>
            <button onclick="stopJob()" style="width: auto; background: #e74c3c;">Stop</button>
        </div>
    </div>

    <div id="file_viewer">
        <div>
            <span class="close-btn" onclick="closeFile()">× Close</span>
            <h2 id="viewing_filename" style="margin-top: 0; color: #3498db;">File View</h2>
            <hr style="border: 0; border-top: 1px solid #444;">
        </div>

        <div id="file_content">Loading...</div>

        <iframe id="file_iframe"></iframe>
    </div>

    <script>
        let currentJob = null;

        async function fetchStatus() {
            try {
                const res = await fetch('/status');
                const data = await res.json();

                // 1. Update Job Buttons & Colors
                let jobHtml = '';
                for (const [name, info] of Object.entries(data)) {
                    let stateClass = '';
                    const stat = info.status.toLowerCase();
                    if (stat.includes('thinking')) stateClass = 'state-thinking';
                    else if (stat.includes('executing')) stateClass = 'state-executing';
                    else if (stat.includes('waiting')) stateClass = 'state-waiting';
                    else if (stat.includes('error')) stateClass = 'state-error';
                    else if (stat.includes('fetching')) stateClass = 'state-fetching';

                    let cls = (name === currentJob) ? `job-btn active-job ${stateClass}` : `job-btn ${stateClass}`;
                    jobHtml += `<button class="${cls}" onclick="selectJob('${name.replace(/'/g, "\\'")}')">${name} [${info.status}]</button>`;
                }
                document.getElementById('job_list').innerHTML = jobHtml;

                // 2. Update Logs & File List for Selected Job
                if (currentJob && data[currentJob]) {
                    const jobData = data[currentJob];
                    document.getElementById('current_job_title').innerText = "Logs: " + currentJob;
                    document.getElementById('current_job_status').innerText = "Status: " + jobData.status;

                    // NEW: Update Token Counts and Calculate Cost
                    document.getElementById('token_counts').style.display = 'inline-block';

                    const inTokens = jobData.input_tokens || 0;
                    const outTokens = jobData.output_tokens || 0;

                    // Kimi 2.5 Pricing Calculation
                    const cost = ((inTokens / 1000000) * 0.60) + ((outTokens / 1000000) * 3.00);

                    document.getElementById('tokens_in').innerText = inTokens.toLocaleString();
                    document.getElementById('tokens_out').innerText = outTokens.toLocaleString();
                    document.getElementById('total_cost').innerText = cost.toFixed(4); // Show up to 4 decimal places
                    // Render Logs with Markdown (Double backslash for Python string injection fix)
                    const logsDiv = document.getElementById('logs');
                    const wasAtBottom = logsDiv.scrollHeight - logsDiv.scrollTop <= logsDiv.clientHeight + 10;

                    const rawLogText = jobData.logs.join('\\n');
                    logsDiv.innerHTML = marked.parse(rawLogText, { breaks: true, gfm: true });

                    if (wasAtBottom) logsDiv.scrollTop = logsDiv.scrollHeight;

                    // Populate the Main Files list with the requested setup
                    document.getElementById('files_title').style.display = 'block';
                    const mainFiles = [
                        'submission.csv',
                        'experiment_memory.txt',
                        'evaluate_metric.py',
                        'deep_eda_report.html',
                        'eda_summary.txt',
                        'competition_summary.txt'
                    ];
                    let fileHtml = '';
                    mainFiles.forEach(f => {
                        fileHtml += `<div class="file-link" onclick="viewFile('${f}')">📄 ${f}</div>`;
                    });
                    document.getElementById('file_list').innerHTML = fileHtml;
                }
            } catch (err) {
                console.error("Error fetching status:", err);
            }
        }

        function selectJob(name) {
            currentJob = name;
            fetchStatus();
        }

        async function startJob() {
            const comp = document.getElementById('comp_name').value;
            const iters = document.getElementById('start_iterations').value;
            if (!comp) return;
            await fetch('/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({competition: comp, iterations: iters})
            });
            document.getElementById('comp_name').value = '';
            selectJob(comp);
        }

        async function sendFeedback(action) {
            const msg = document.getElementById('feedback_msg').value;
            const iters = document.getElementById('run_iterations').value;
            if (!currentJob || !msg) return;
            await fetch('/interact', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({competition: currentJob, message: msg, action: action, iterations: iters})
            });
            document.getElementById('feedback_msg').value = '';
            fetchStatus();
        }

        async function stopJob() {
            if (!currentJob) return;
            await fetch('/stop', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({competition: currentJob})
            });
            fetchStatus();
        }

        async function viewFile(filename) {
            if (!currentJob) return;

            document.getElementById('viewing_filename').innerText = filename;
            const contentDiv = document.getElementById('file_content');
            const iframe = document.getElementById('file_iframe');

            // Open the slide-over panel
            document.getElementById('file_viewer').classList.add('open');

            if (filename.endsWith('.html')) {
                // Hide the text viewer, show the iframe
                contentDiv.style.display = 'none';
                iframe.style.display = 'block';
                // Serve the HTML directly through the Flask endpoint
                iframe.src = `/get_file?competition=${currentJob}&filename=${filename}`;
            } else {
                // Hide the iframe, show the text viewer
                iframe.style.display = 'none';
                contentDiv.style.display = 'block';
                contentDiv.innerText = "Fetching file content from workspace...";

                // Fetch text data as JSON
                const res = await fetch(`/get_file?competition=${currentJob}&filename=${filename}`);
                const data = await res.json();

                if (data.content) {
                    contentDiv.innerText = data.content;
                } else {
                    contentDiv.innerText = "⚠️ File not found. The agent might still be writing it, or it was saved in the wrong directory.";
                }
            }
        }

        function closeFile() {
            document.getElementById('file_viewer').classList.remove('open');
            // Clear iframe src so it stops rendering/playing media in background
            setTimeout(() => { document.getElementById('file_iframe').src = ''; }, 400);
        }

        // Poll backend every 2 seconds
        setInterval(fetchStatus, 2000);
    </script>
</body>
</html>
"""

# Load the environment variables
load_dotenv("keys.env")

# --- TELEGRAM SETUP ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
AUTHORIZED_CHAT_ID = os.getenv("AUTHORIZED_CHAT_ID")

bot = telebot.TeleBot(TELEGRAM_TOKEN)


def is_authorized(message):
    return str(message.chat.id) == AUTHORIZED_CHAT_ID


# --- NEW: Helper to find job by Number or Name ---
def resolve_comp_name(identifier):
    if not active_jobs: return None
    # If user types a number (e.g., "1")
    if identifier.isdigit():
        idx = int(identifier) - 1
        keys = list(active_jobs.keys())
        if 0 <= idx < len(keys):
            return keys[idx]
    # Fallback: if they type a single-word comp name
    elif identifier in active_jobs:
        return identifier
    return None


@bot.message_handler(commands=['status'])
def handle_status(message):
    if not is_authorized(message): return

    if not active_jobs:
        bot.reply_to(message, "No active Kaggle swarms running.")
        return

    reply = "📊 *Active Swarms:*\n"
    for i, (name, agent) in enumerate(active_jobs.items(), 1):
        reply += f"*{i}.* `{name}`\n   Status: {agent.status} (Exp: {agent.experiment_count}/{agent.max_experiments})\n"

    reply += "\n💡 *Tip:* Use the ID number instead of the name! (e.g. `/ask 1 What's up?`)"
    bot.reply_to(message, reply, parse_mode="Markdown")


@bot.message_handler(commands=['run'])
def handle_run(message):
    if not is_authorized(message): return

    # Split into exactly 3 parts: /run, ID, and everything else
    tokens = message.text.split(" ", 2)
    if len(tokens) < 2:
        bot.reply_to(message, "Usage: `/run <ID> <iterations> <instructions>`\nExample: `/run 1 10 Try LightGBM`",
                     parse_mode="Markdown")
        return

    identifier = tokens[1]
    comp_name = resolve_comp_name(identifier)

    if not comp_name:
        bot.reply_to(message, "⚠️ Job not found. Check `/status` for valid IDs.", parse_mode="Markdown")
        return

    # Parse iterations and instructions from the rest of the message
    rest_of_msg = tokens[2] if len(tokens) > 2 else ""
    sub_tokens = rest_of_msg.split(" ", 1)

    if sub_tokens and sub_tokens[0].isdigit():
        iters = int(sub_tokens[0])
        msg_text = sub_tokens[1] if len(sub_tokens) > 1 else "Keep going."
    else:
        iters = 5  # Default
        msg_text = rest_of_msg if rest_of_msg else "Keep going."

    agent = active_jobs[comp_name]

    # 1. Log the incoming command to the Web UI
    agent.log(f"📱 **Telegram Command:** `/run` - Resuming for {iters} iterations. Feedback: _{msg_text}_")

    if agent.status == "Waiting for User":
        bot.reply_to(message, f"🚀 Resuming `{comp_name}` for {iters} iterations with feedback:\n_{msg_text}_",
                     parse_mode="Markdown")
        agent.provide_feedback(msg_text, iterations=iters)
    else:
        bot.reply_to(message, f"⏳ `{comp_name}` is currently busy ({agent.status}).")


@bot.message_handler(commands=['ask'])
def handle_ask(message):
    if not is_authorized(message): return

    # Split into 3 parts: /ask, ID, and the whole question
    tokens = message.text.split(" ", 2)
    if len(tokens) < 3:
        bot.reply_to(message, "Usage: `/ask <ID> <question>`\nExample: `/ask 1 What did you learn so far?`",
                     parse_mode="Markdown")
        return

    identifier = tokens[1]
    question = tokens[2]

    comp_name = resolve_comp_name(identifier)
    if not comp_name:
        bot.reply_to(message, "⚠️ Job not found. Check `/status` for valid IDs.", parse_mode="Markdown")
        return

    agent = active_jobs[comp_name]

    # 1. Log the incoming command to the Web UI
    agent.log(f"📱 **Telegram Command:** `/ask` - Question: _{question}_")

    if agent.status == "Waiting for User":
        bot.reply_to(message, f"🤔 Asking `{comp_name}`... Please wait for a reply.", parse_mode="Markdown")
        threading.Thread(target=agent.chat_only, args=(question,), daemon=True).start()
    else:
        bot.reply_to(message, f"⏳ `{comp_name}` is currently busy ({agent.status}).")


@bot.message_handler(commands=['stop'])
def handle_stop(message):
    if not is_authorized(message): return

    tokens = message.text.split(" ", 1)
    if len(tokens) < 2:
        bot.reply_to(message, "Usage: `/stop <ID>`", parse_mode="Markdown")
        return

    identifier = tokens[1].strip()
    comp_name = resolve_comp_name(identifier)

    if comp_name:
        agent = active_jobs[comp_name]

        # 1. Log the incoming command to the Web UI
        agent.log(f"📱 **Telegram Command:** `/stop` - Stop requested via Telegram.")

        agent.stop_requested = True
        bot.reply_to(message, f"🛑 Stop requested for `{comp_name}`. It will pause after its current task.",
                     parse_mode="Markdown")
    else:
        bot.reply_to(message, "⚠️ Job not found. Check `/status` for valid IDs.", parse_mode="Markdown")


# ----------------------

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route('/start', methods=['POST'])
def start():
    """Initializes a new KaggleSwarmAgent and starts it in a background thread."""
    comp_input = request.json['competition']
    iterations = int(request.json.get('iterations', 5))

    # Determine a clean name for the job dictionary and UI
    if comp_input.startswith("http"):
        match = re.search(r"competitions/([^/]+)", comp_input)
        comp_key = match.group(1) if match else comp_input
    else:
        comp_key = comp_input

    if comp_key not in active_jobs:
        # Pass the original input to the agent
        agent = KaggleSwarmAgent(comp_input)
        agent.max_experiments = iterations
        active_jobs[comp_key] = agent

        agent.job_id = list(active_jobs.keys()).index(comp_key) + 1

        threading.Thread(target=agent.start_job, daemon=True).start()
    return jsonify({"status": "started"})


@app.route('/status', methods=['GET'])
def get_status():
    """Returns the status, logs, and token usage of all running agents."""
    state = {
        name: {
            "status": agent.status,
            "logs": agent.logs[-150:],  # Send last 150 lines to prevent UI lag
            # --- NEW: Expose tokens (using getattr for safety) ---
            "input_tokens": getattr(agent, 'input_tokens', 0),
            "output_tokens": getattr(agent, 'output_tokens', 0)
        }
        for name, agent in active_jobs.items()
    }
    return jsonify(state)


@app.route('/interact', methods=['POST'])
def interact():
    """Receives feedback from the UI and resumes or chats based on the action."""
    comp = request.json['competition']
    msg = request.json['message']
    action = request.json.get('action', 'resume')
    iterations = int(request.json.get('iterations', 5))

    if comp in active_jobs:
        agent = active_jobs[comp]
        if agent.status == "Waiting for User":
            if action == 'ask':
                threading.Thread(target=agent.chat_only, args=(msg,), daemon=True).start()
            else:
                agent.provide_feedback(msg, iterations)
            return jsonify({"status": "resumed"})
        else:
            return jsonify({"error": "Agent is currently busy running. Stop it first."}), 400

    return jsonify({"error": "Job not found"}), 404


@app.route('/stop', methods=['POST'])
def stop():
    """Tells the agent to break its evolution loop safely."""
    comp = request.json['competition']
    if comp in active_jobs:
        agent = active_jobs[comp]
        agent.stop_requested = True
        agent.status = "Stopping..."
        agent.log("🛑 Stop requested. The agent will pause after finishing its current step.")
        return jsonify({"status": "stopping"})
    return jsonify({"error": "Job not found"}), 404


@app.route('/get_file', methods=['GET'])
def get_file():
    """Serves a specific file from the root of the agent's workspace or working folder."""
    comp = request.args.get('competition')
    filename = request.args.get('filename')

    if comp and filename:
        safe_filename = os.path.basename(filename)
        base_dir = os.path.dirname(os.path.abspath(__file__))
        directory = os.path.join(base_dir, "competitions", comp)
        filepath = os.path.join(directory, safe_filename)

        # Fallback for sidebar files written to working directory
        if not os.path.exists(filepath):
            working_dir = os.path.join(directory, "working")
            working_filepath = os.path.join(working_dir, safe_filename)
            if os.path.exists(working_filepath):
                directory = working_dir
                filepath = working_filepath

        if os.path.exists(filepath):
            if safe_filename.endswith('.html'):
                return send_from_directory(directory, safe_filename)

            with open(filepath, 'r', encoding='utf-8') as f:
                return jsonify({"content": f.read()})

    return jsonify({"error": "File not found"}), 404


if __name__ == '__main__':
    print("📱 Starting Telegram Bot Listener...")
    threading.Thread(target=bot.infinity_polling, daemon=True).start()

    print("🌐 Starting Kaggle Swarm Web UI on http://127.0.0.1:5000")
    app.run(debug=True, port=5000, use_reloader=False)
