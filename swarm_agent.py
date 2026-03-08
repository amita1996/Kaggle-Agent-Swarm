import subprocess
import json
import concurrent.futures
from openai import OpenAI
import re
import requests
import threading
from scrape_data import get_context_data
from utils import download_kaggle_data
import os
from dotenv import load_dotenv

load_dotenv("keys.env")

API_KEY = os.getenv("KIMI_API_KEY")
BASE_URL = "https://api.kimi.com/coding/v1"


class KaggleSwarmAgent:
    def __init__(self, comp_input):
        self.original_input = comp_input

        self.user_directives = []
        self.base_system_prompt = ""
        self.comp_summary = ""

        if comp_input.startswith("http"):
            match = re.search(r"competitions/([^/]+)", comp_input)
            self.comp_name = match.group(1) if match else "unknown_comp"
        else:
            self.comp_name = comp_input

        self.status = "Initializing"
        self.job_id = "?"
        self.logs = []
        self.messages = []
        self.experiment_count = 0
        self.max_experiments = 5

        self.input_tokens = 0
        self.output_tokens = 0

        self.stop_requested = False

        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.work_dir = os.path.join(base_dir, "competitions", self.comp_name)
        os.makedirs(self.work_dir, exist_ok=True)

        # Swarm Directories
        self.working_dir = os.path.join(self.work_dir, "working")
        self.test_dir = os.path.join(self.work_dir, "test")
        os.makedirs(self.working_dir, exist_ok=True)
        os.makedirs(self.test_dir, exist_ok=True)

        self.client = OpenAI(
            api_key=API_KEY,
            base_url=BASE_URL,
            default_headers={"User-Agent": "KimiCLI/1.5"}
        )

        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": "delegate_experiment",
                    "description": "Spawns an Experiment Agent to test a new hypothesis in an isolated 'test' subdirectory. Call this multiple times to test multiple ideas in parallel.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "experiment_name": {"type": "string",
                                                "description": "Short, safe name (no spaces/special chars) for the experiment directory."},
                            "hypothesis": {"type": "string",
                                           "description": "Detailed instructions on what the agent should code and test."}
                        },
                        "required": ["experiment_name", "hypothesis"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "list_files",
                    "description": "Lists all files in the working directory to understand the current modular project structure.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "delegate_integration",
                    "description": "Spawns the Main Agent to integrate successful experiment code from 'test' into the main pipeline in 'working'.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "experiment_name": {"type": "string",
                                                "description": "Name of the successful experiment to integrate."},
                            "integration_instructions": {"type": "string",
                                                         "description": "Instructions for the Main Agent on what files to read from 'test' and what to update in 'working'."}
                        },
                        "required": ["experiment_name", "integration_instructions"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                        "name": "write_file",
                        "description": "Creates or updates a specific Python file (module) in the working directory. Use this to update individual files like features.py or train.py.",                    "parameters": {
                        "type": "object",
                        "properties": {
                            "filename": {"type": "string", "description": "Name of the file"},
                            "code": {"type": "string", "description": "The complete Python code to write."}
                        },
                        "required": ["filename", "code"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Reads the current contents of a file in the working directory.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "filename": {"type": "string", "description": "Name of the file to read."}
                        },
                        "required": ["filename"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "execute_script",
                    "description": "Executes a specific Python script in the working directory and returns output.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "filename": {"type": "string", "description": "The script to run (e.g., 'main.py')."}
                        },
                        "required": ["filename"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "revert_workspace",
                    "description": "Reverts the working directory to the last known working Git commit. Use this if recent code edits broke the pipeline.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "record_experiment",
                    "description": "Records the methodology and validation score of an experiment to the Orchestrator's long-term memory.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "experiment_name": {"type": "string",
                                                "description": "Name or version of the model/experiment."},
                            "methodology": {"type": "string",
                                            "description": "Summary of features, model, and hyperparameters used."},
                            "val_score": {"type": "number",
                                          "description": "The score achieved on the holdout validation set."},
                            "learnings": {"type": "string",
                                          "description": "What worked, what failed, and what to try next."}
                        },
                        "required": ["experiment_name", "methodology", "val_score", "learnings"]
                    }
                }
            },
            {
                "type": "builtin_function",
                "function": {
                    "name": "$web_search"
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "finish_eda_phase",
                    "description": "Transitions the swarm to the Iterative Modeling Phase.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "eda_summary": {
                                "type": "string",
                                "description": "A detailed summary of your EDA findings and CV setup."
                            }
                        },
                        "required": ["eda_summary"]
                    }
                }
            }
        ]

    def log(self, message):
        formatted_msg = f"[{self.comp_name}] {message}"
        print(formatted_msg)
        self.logs.append(message)

    def prune_memory(self, max_messages=8):
        if len(self.messages) <= max_messages:
            return

        original_len = len(self.messages)
        system_prompt = self.messages[0]
        cut_idx = len(self.messages) - (max_messages - 1)

        while cut_idx > 1 and self.messages[cut_idx].get('role') == 'tool':
            cut_idx -= 1
        while cut_idx > 1 and self.messages[cut_idx - 1].get('role') == 'assistant' and self.messages[cut_idx - 1].get(
                'tool_calls'):
            cut_idx -= 1

        recent_messages = self.messages[cut_idx:]
        self.messages = [system_prompt] + recent_messages
        self.log(f"🧹 Memory safely pruned from {original_len} to {len(self.messages)} messages.")

    def record_experiment(self, experiment_name, methodology, val_score, learnings):
        self.experiment_count += 1
        memory_file = os.path.join(self.work_dir, "experiment_memory.txt")

        entry = f"""
                === Experiment {self.experiment_count}: {experiment_name} ===
                Methodology: {methodology}
                Validation Score: {val_score}
                Learnings/Next Steps: {learnings}
                -----------------------------------
        """
        with open(memory_file, "a", encoding="utf-8") as f:
            f.write(entry)

        self.log(f"🧠 MEMORY UPDATED: {experiment_name} scored {val_score}")
        return f"Experiment recorded successfully. Total experiments so far: {self.experiment_count}"

    def initial_setup(self):
        self.status = "Fetching Data"
        self.log("🔍 Fetching competition context and past solutions...")

        comp_text, sol_text_list, kaggle_url = get_context_data(self.original_input)

        with open(os.path.join(self.work_dir, "competition_description.txt"), "w", encoding="utf-8") as f:
            f.write(comp_text)

        solutions_dir = os.path.join(self.work_dir, "past_solutions")
        os.makedirs(solutions_dir, exist_ok=True)
        for i, sol in enumerate(sol_text_list):
            with open(os.path.join(solutions_dir, f"solution_{i + 1}.txt"), "w", encoding="utf-8") as f:
                f.write(sol)

        data_dir = os.path.join(self.work_dir, "data")
        self.log(f"📥 Downloading data to '{data_dir}'...")
        download_kaggle_data(kaggle_url, path=data_dir)
        self.log("✅ Workspace & Data ready.")

        self.status = "Summarizing Context"
        self.log("🧠 Extracting competition summary for system prompt...")

        summary_prompt = f"You are an expert Data Scientist. Read this competition description and provide a concise summary of the objective, the dataset schema (the exact files, whats in each file and in which relative directory they are in), the exact evaluation metric (keep all exact info on the metric, so there wont be any misunderstandings) and the exact submission.csv file expected.\n\n{comp_text}"

        try:
            summary_response = self.client.chat.completions.create(
                model="kimi-k2.5",
                messages=[{"role": "user", "content": summary_prompt}],
                temperature=0.3
            )

            if summary_response.usage:
                self.input_tokens += summary_response.usage.prompt_tokens
                self.output_tokens += summary_response.usage.completion_tokens

            self.comp_summary = summary_response.choices[0].message.content
        except Exception as e:
            self.log(f"⚠️ Failed to generate summary: {e}")
            self.comp_summary = "Summary generation failed. Read competition_description.txt directly."

        self.log(f'Competition summary generated:\n{self.comp_summary}')

        summary_file = os.path.join(self.work_dir, "competition_summary.txt")
        with open(summary_file, "w", encoding="utf-8") as f:
            f.write(self.comp_summary)
        self.log(f"💾 Saved competition summary to {summary_file}")

        subprocess.run(["git", "init"], cwd=self.working_dir, capture_output=True)
        self.log("🔧 Initialized Git repository in the working directory.")

        self.base_system_prompt = f"""You are Kimi K2.5, a Kaggle Grandmaster Orchestrator. 
                You are currently in PHASE 1: THE VAULT & EDA.

                --- 🏆 COMPETITION CONTEXT ---
                {self.comp_summary}

                --- 🗂️ WORKSPACE ---
                You are executing code inside: {self.working_dir}
                The raw competition data is located in: {data_dir}
                RULE: ALWAYS use absolute paths to read data.

                --- 🛑 PHASE 1 PROTOCOL (CRITICAL) ---
                DO NOT TRAIN ANY PREDICTIVE MODELS YET. Your ONLY jobs right now are:
                1. Establish a MODULAR project structure. You must separate logic into distinct files (e.g., `config.py`, `features.py`, `train.py`, `evaluate.py`). DO NOT write single monolithic scripts.
                2. Write an EDA script to generate a report and save it to deep_eda_report.html (Make sure it is saved in {self.working_dir}). Dont forget to show how the raw data looks like
                3. Write a script to establish a robust Cross-Validation framework (Make sure there is no leakage! this is a critical phase. if its temporal data, make sure the validation set takes that into account). Save fold assignments to a CSV.
                4. Implement the exact scoring metric inside `evaluate_metric.py` in {self.working_dir}.                
                
                Once you have successfully executed these scripts and verified the modular structure, call `finish_eda_phase`.
                """

        self.messages = [
            {"role": "system", "content": self.base_system_prompt},
            {"role": "user",
             "content": "Initiate Swarm Phase 1. Perform deep EDA, setup CV folds, and then call finish_eda_phase."}
        ]

    def finish_eda_phase(self, eda_summary):
        self.log(f"🎯 EDA Phase Complete! Handoff summary:\n{eda_summary}...")

        summary_path = os.path.join(self.work_dir, "eda_summary.txt")
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(eda_summary)
        self.log(f"💾 Saved EDA summary to {summary_path}")

        self.current_phase = "modeling"
        data_dir = os.path.join(self.work_dir, "data")

        # --- PHASE 2 PROMPT: MULTI-AGENT ORCHESTRATION ---
        self.base_system_prompt = f"""You are Kimi K2.5, the Swarm Orchestrator for this Kaggle Competition.
                You are currently in PHASE 2: MULTI-AGENT EVOLUTION LOOP.

                --- 🗂️ WORKSPACES & CONTEXT ---
                Main Pipeline Directory (Working): {self.working_dir}
                Experiments Directory (Test): {self.test_dir}
                Raw Data: {data_dir}

                --- 🏆 COMPETITION CONTEXT ---
                {self.comp_summary}

                EDA & CV Setup (Already complete):
                {eda_summary}

                --- 🐛 DEBUGGING PROTOCOL (CRITICAL) ---
                If an Experiment Agent reports an execution failure, crash, "path issues", or incomplete code:
                DO NOT ABANDON THE HYPOTHESIS. Do not move on to a new idea.
                1. Call `delegate_experiment` again using the EXACT SAME `experiment_name` as the failed run. This drops a new agent into the same folder containing the broken code.
                2. In the `hypothesis` parameter, provide strict debugging instructions (e.g., "Read your existing script, fix the FileNotFoundError by using absolute paths to the data directory, and re-run to get the validation score").

                --- 🛑 WORKSPACE RULES ---
                DO NOT write throwaway scripts just to explore directories or check dataframe shapes (e.g., `explore.py` or `find.py`). 
                If you need to see files, use your `list_files` tool. If you need to check data shapes, write a comprehensive EDA script or print the shapes within your main training scripts. Do not litter the workspace with 10-line debugging scripts.

                --- 🥇 SWARM DELEGATION PROTOCOL (CRITICAL) ---
                You are the Manager. DO NOT write or execute code directly using `write_file` or `execute_script` anymore.
                Instead, you orchestrate a swarm to achieve a Gold Medal score:
                1. Formulate multiple hypotheses.
                2. Use `delegate_experiment` to assign these hypotheses to Experiment Agents. 
                3. Read their returned results and validation scores.
                4. MANDATORY CHECK: Compare the Experiment Agent's validation score against your Experiment Memory
                5. INTEGRATION DECISION: ONLY use `delegate_integration` if the new experiment's score is STRICTLY BETTER than the previous best score in your memory. Do not integrate failed or sideways experiments.
                6. Use `record_experiment` to log all methodology and OOF scores so you don't lose track.
                7. Extract a submission.csv - that is updated every time that you improve the score.
                8. Avoid using or training neural networks until being told otherwise
                9. Use a 'static' model for all experiments (such as LGBM) until you reach iteration 10 - optimize using feature engineering and other data science tricks. afterwards, you can optimize modeling as well.
                """

        if self.messages and self.messages[0].get("role") == "system":
            self.messages[0]["content"] = self.base_system_prompt

        return "Phase 1 complete. Phase 2 initiated. Do not write code directly anymore. Formulate hypotheses and use `delegate_experiment` to spawn your testing swarm."

    # --- SUB-AGENT ORCHESTRATION LOGIC ---
    def delegate_experiment(self, experiment_name, hypothesis):
        safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', experiment_name)
        exp_dir = os.path.join(self.test_dir, f"exp_{safe_name}")
        os.makedirs(exp_dir, exist_ok=True)

        # --- FIX: FETCH MEMORY FOR SUB-AGENT ---
        memory_file = os.path.join(self.work_dir, "experiment_memory.txt")
        memory_content = "No experiments recorded yet."
        if os.path.exists(memory_file):
            with open(memory_file, "r", encoding="utf-8") as f:
                memory_content = f.read()

        self.log(f"🧪 [Exp-Agent: {experiment_name}] Started: {hypothesis} in {exp_dir}")

        sys_prompt = f"""You are an Experiment Agent in a Kaggle Swarm.
        Task: {hypothesis}
        
        --- 🐍 IMPORTING MODULES (CRITICAL) ---
        To import scripts from the Working Directory (like the metric or features), you MUST append it to your path at the top of your scripts:
        import sys
        sys.path.append("{self.working_dir}")
        from evaluate_metric import your_metric_function

        --- 🗂️ ABSOLUTE PATHS (CRITICAL) ---
        Your Workspace (Write your scripts here): {exp_dir}
        Data Directory (Raw competition data): {os.path.join(self.work_dir, "data")}
        Working Directory (Contains folds.csv and Phase 1 scripts): {self.working_dir}
        Metric is in {os.path.join(self.working_dir, 'evaluate_metric.py')}

        RULE: NEVER guess relative paths like '../working'. ALWAYS use the absolute paths provided above to read data and folds.

        --- DATA & COMPETITION CONTEXT ---
        {self.comp_summary}

        --- 🏆 CURRENT LEADERBOARD & PAST EXPERIMENTS ---
        {memory_content}

        CRITICAL INSTRUCTION: Review the past experiments above. Your goal is to BEAT the best validation score listed while performing the hypothesis given to you.
        Write your experimental Python scripts, execute them, and report your validation score compared to the previous best. Do not modify the main working directory.
        """

        return self._run_sub_agent(sys_prompt, f"Exp-{experiment_name}", exp_dir)

    def delegate_integration(self, experiment_name, integration_instructions):
        self.log(f"🛠️ [Main-Agent] Integrating {experiment_name} into modular pipeline...")

        sys_prompt = f"""You are the Main Integration Agent, acting as a Senior Software Engineer.
        Task: {integration_instructions}
        Target Directory (Working): {self.working_dir}
        Source Directory (Test): {self.test_dir}
        Metric is in {os.path.join(self.work_dir, "evaluate_metric.py")}


        --- 🛑 INTEGRATION PROTOCOL ---
        The main pipeline in the Target Directory is MODULAR (e.g., features.py, train.py, models.py).
        1. Do NOT just copy the experiment as a single monolithic script.
        2. Read the successful experiment code from the Source Directory.
        3. Use `sub_list_files` (if available) and `sub_read_file` to understand the current state of the main pipeline modules.
        4. Deconstruct the experiment and inject the code into the correct existing modules (e.g., add new feature engineering logic to `features.py`, update model parameters in `models.py`, update the main loop in `train.py`).
        5. Execute `train.py` (or the main entry point) to verify the integration didn't break anything, and report the final status.
        6. Extract a submission.csv file each time you manage to improve the competition metric.
        """

        return self._run_sub_agent(sys_prompt, "Main-Agent", self.working_dir)
    def _run_sub_agent(self, sys_prompt, agent_name, workspace, max_steps=30):
        """Internal execution loop for sub-agents with scoped tools and token tracking."""
        messages = [{"role": "system", "content": sys_prompt}]

        sub_tools = [
            {
                "type": "function",
                "function": {
                    "name": "sub_write_file",
                    "description": "Writes code to a file in your designated workspace.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "filename": {"type": "string"},
                            "code": {"type": "string"}
                        },
                        "required": ["filename", "code"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "sub_list_files",
                    "description": "Lists all files and directories in your workspace to understand the project structure.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "sub_read_file",
                    "description": "Reads a file. You can pass absolute paths to read from other directories if needed.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "filepath": {"type": "string",
                                         "description": "Absolute path, or relative to your workspace."}
                        },
                        "required": ["filepath"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "sub_execute_script",
                    "description": "Executes a Python script in your workspace and returns stdout/stderr.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "filename": {"type": "string"}
                        },
                        "required": ["filename"]
                    }
                }
            }
        ]

        for step in range(max_steps):
            try:
                response = self.client.chat.completions.create(
                    model="kimi-k2.5",
                    messages=messages,
                    tools=sub_tools,
                    tool_choice="auto",
                    temperature=0.7
                )

                if response.usage:
                    self.input_tokens += response.usage.prompt_tokens
                    self.output_tokens += response.usage.completion_tokens

                msg = response.choices[0].message
                messages.append(msg.model_dump(exclude_none=True))

                if not msg.tool_calls:
                    return f"[{agent_name} Report] {msg.content}"

                tool_results = []
                for tool_call in msg.tool_calls:
                    name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments)

                    try:
                        if name == "sub_write_file":
                            filepath = os.path.join(workspace, args["filename"])
                            with open(filepath, "w", encoding="utf-8") as f:
                                f.write(args["code"])
                            output = f"Successfully wrote {args['filename']}."
                        elif name == "sub_read_file":
                            filepath = args["filepath"]
                            if not os.path.isabs(filepath):
                                filepath = os.path.join(workspace, filepath)
                            with open(filepath, "r", encoding="utf-8") as f:
                                content = f.read()
                                # Add truncation here too
                                if len(content) > 3000:
                                    content = content[:1500] + "\n\n... [FILE TRUNCATED FOR LENGTH] ...\n\n" + content[
                                                                                                               -1500:]
                                output = f"--- Contents of {filepath} ---\n" + content

                        elif name == "sub_list_files":
                            try:
                                files = os.listdir(workspace)
                                output = f"Contents of {workspace}:\n" + "\n".join(files)
                            except Exception as e:
                                output = f"Error listing files: {str(e)}"

                        elif name == "sub_execute_script":
                            filepath = os.path.join(workspace, args["filename"])
                            res = subprocess.run(["python", filepath], capture_output=True, text=True, cwd=workspace)
                            output = f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
                            if len(output) > 2000:
                                output = output[:500] + "\n...[TRUNCATED]...\n" + output[-1400:]
                    except Exception as e:
                        output = f"Error executing {name}: {str(e)}"

                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": name,
                        "content": output
                    })
                messages.extend(tool_results)
            except Exception as loop_e:
                return f"[{agent_name} Error] Exception during execution: {loop_e}"

        messages.append({"role": "user",
                         "content": "You have reached your maximum operational steps. Please provide a concise summary of your findings and the final metric achieved."})
        final_res = self.client.chat.completions.create(model="kimi-k2.5", messages=messages, temperature=0.7)

        if final_res.usage:
            self.input_tokens += final_res.usage.prompt_tokens
            self.output_tokens += final_res.usage.completion_tokens

        return f"[{agent_name} Final Report] {final_res.choices[0].message.content}"

    def _auto_commit(self, message):
        subprocess.run(["git", "add", "."], cwd=self.working_dir, capture_output=True)
        subprocess.run(["git", "commit", "-m", message], cwd=self.working_dir, capture_output=True)

    def save_state(self):
        state_file = os.path.join(self.work_dir, "agent_state.json")
        state_data = {
            "status": self.status,
            "experiment_count": self.experiment_count,
            "max_experiments": self.max_experiments,
            "messages": self.messages,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens
        }
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state_data, f, indent=4)
        self.log("💾 State checkpoint saved.")

    def load_state(self) -> bool:
        state_file = os.path.join(self.work_dir, "agent_state.json")
        if os.path.exists(state_file):
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    state_data = json.load(f)

                self.status = state_data.get("status", "Initialized")
                self.experiment_count = state_data.get("experiment_count", 0)
                self.max_experiments = state_data.get("max_experiments", 5)
                self.messages = state_data.get("messages", [])
                self.input_tokens = state_data.get("input_tokens", 0)
                self.output_tokens = state_data.get("output_tokens", 0)

                self.log(f"🔄 Resumed from existing state. Experiments so far: {self.experiment_count}")
                return True
            except Exception as e:
                self.log(f"⚠️ Failed to load state: {e}")
                return False
        return False

    def send_pause_summary(self, reason="Limit Reached"):
        self.log("📝 Generating summary of accomplishments for Telegram...")
        temp_messages = self.messages + [
            {"role": "user",
             "content": "The run loop has paused. Briefly summarize what was accomplished in the recent iterations and what the immediate next steps should be. Do not use tools. Be concise."}
        ]
        try:
            response = self.client.chat.completions.create(
                model="kimi-k2.5",
                messages=temp_messages,
                temperature=0.7
            )

            if response.usage:
                self.input_tokens += response.usage.prompt_tokens
                self.output_tokens += response.usage.completion_tokens

            summary_text = response.choices[0].message.content

            msg = (
                f"⏸️ Swarm Paused: {self.comp_name} (ID: {self.job_id})\n"
                f"Reason: {reason}\n"
                f"Completed {self.experiment_count}/{self.max_experiments} experiments.\n\n"
                f"📝 Accomplished & Next Steps:\n{summary_text}\n\n"
                f"Reply with:\n"
                f"/run {self.job_id} 5 Try XGBoost\n"
                f"/ask {self.job_id} What was the best score?"
            )
            self.notify_telegram(msg)
        except Exception as e:
            self.log(f"⚠️ Failed to generate summary: {e}")
            msg = (
                f"⏸️ Swarm Paused: {self.comp_name} (ID: {self.job_id})\n"
                f"Reason: {reason}\n"
                f"Completed {self.experiment_count}/{self.max_experiments} experiments.\n\n"
                f"Reply with:\n"
                f"/run {self.job_id} 5 Try XGBoost\n"
                f"/ask {self.job_id} What was the best score?"
            )
            self.notify_telegram(msg)

    def run_loop(self):
        while True:
            if self.stop_requested:
                self.log("⏸️ Agent stopped by user.")
                self.status = "Waiting for User"
                self.stop_requested = False
                self.send_pause_summary(reason="Stopped by User")
                break

            if self.experiment_count >= self.max_experiments:
                self.log(f"⏸️ Reached limit. Pausing.")
                self.status = "Waiting for User"
                self.send_pause_summary(reason="Iteration Limit Reached")
                break

            self.prune_memory(max_messages=20)
            self.save_state()

            self.status = "Thinking..."
            self.log("🧠 Orchestrator is thinking...")


            memory_file = os.path.join(self.work_dir, "experiment_memory.txt")
            memory_content = "No experiments recorded yet."
            if os.path.exists(memory_file):
                with open(memory_file, "r", encoding="utf-8") as f:
                    memory_content = f.read()

            # Keep the base prompt, but append the dynamic memory
            self.messages[0]["content"] = self.base_system_prompt + f"\n\n--- 🧠 EXPERIMENT MEMORY (Current Best Scores) ---\n{memory_content}"

            response = self.client.chat.completions.create(
                model="kimi-k2.5",
                messages=self.messages,
                tools=self.tools,
                tool_choice="auto",
                temperature=0.8,
                extra_body={"mode": "agent_swarm"},
            )

            if response.usage:
                self.input_tokens += response.usage.prompt_tokens
                self.output_tokens += response.usage.completion_tokens

            msg = response.choices[0].message
            self.messages.append(msg.model_dump(exclude_none=True))

            if msg.content:
                self.log(f"🗣️ Orchestrator: {msg.content}")

            if not msg.tool_calls:
                self.log("⚠️ Orchestrator stopped generating tool calls. Nudging it to continue...")
                self.messages.append({"role": "user",
                                      "content": "Keep going. Use delegate_experiment to test hypotheses or delegate_integration to implement winners."})
                continue

            self.status = "Executing Swarm Actions..."
            self.log(f"🚀 Processing {len(msg.tool_calls)} concurrent action(s)...")
            tool_results = []

            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                future_to_tool = {}
                for tool_call in msg.tool_calls:

                    if tool_call.function.name == "delegate_experiment":
                        args = json.loads(tool_call.function.arguments)
                        future = executor.submit(self.delegate_experiment, args.get("experiment_name"),
                                                 args.get("hypothesis"))
                        future_to_tool[future] = tool_call

                    elif tool_call.function.name == "delegate_integration":
                        args = json.loads(tool_call.function.arguments)
                        future = executor.submit(self.delegate_integration, args.get("experiment_name"),
                                                 args.get("integration_instructions"))
                        future_to_tool[future] = tool_call

                    elif tool_call.function.name == "list_files":
                        future = executor.submit(self.list_files)
                        future_to_tool[future] = tool_call

                    elif tool_call.function.name == "write_file":
                        args = json.loads(tool_call.function.arguments)
                        future = executor.submit(self.write_file, args.get("filename"), args.get("code"))
                        future_to_tool[future] = tool_call

                    elif tool_call.function.name == "read_file":
                        args = json.loads(tool_call.function.arguments)
                        future = executor.submit(self.read_file, args.get("filename"))
                        future_to_tool[future] = tool_call

                    elif tool_call.function.name == "execute_script":
                        args = json.loads(tool_call.function.arguments)
                        future = executor.submit(self.execute_script, args.get("filename"))
                        future_to_tool[future] = tool_call

                    elif tool_call.function.name == "revert_workspace":
                        future = executor.submit(self.revert_workspace)
                        future_to_tool[future] = tool_call

                    elif tool_call.function.name == "record_experiment":
                        args = json.loads(tool_call.function.arguments)
                        future = executor.submit(self.record_experiment,
                                                 args.get("experiment_name"),
                                                 args.get("methodology"),
                                                 float(args.get("val_score", 0)),
                                                 args.get("learnings"))
                        future_to_tool[future] = tool_call

                    elif tool_call.function.name == "$web_search":
                        future = executor.submit(lambda args: args, tool_call.function.arguments)
                        future_to_tool[future] = tool_call

                    elif tool_call.function.name == "finish_eda_phase":
                        args = json.loads(tool_call.function.arguments)
                        future = executor.submit(self.finish_eda_phase, args.get("eda_summary"))
                        future_to_tool[future] = tool_call

                for future in concurrent.futures.as_completed(future_to_tool):
                    tool_call = future_to_tool[future]
                    try:
                        output = future.result()
                    except Exception as exc:
                        output = f"Exception: {exc}"

                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.function.name,
                        "content": output
                    })

            self.messages.extend(tool_results)
            self.save_state()

    def start_job(self):
        try:
            if not self.load_state():
                self.log("🆕 No previous state found. Running initial setup.")
                self.initial_setup()
            self.run_loop()
        except Exception as e:
            self.log(f"❌ FATAL ERROR: {str(e)}")
            self.status = "Error"

    def provide_feedback(self, user_text, iterations=5):
        self.log(f"👤 User Feedback/Directive added: {user_text}")
        self.user_directives.append(user_text)

        directives_text = "\n".join([f"- {d}" for d in self.user_directives])
        new_system_prompt = self.base_system_prompt + f"\n\n--- 🛑 STRICT USER DIRECTIVES (NEVER IGNORE) ---\n{directives_text}"
        self.messages[0]["content"] = new_system_prompt

        self.messages.append(
            {"role": "user", "content": f"New directive applied: {user_text}. Please acknowledge and adapt."})

        self.max_experiments = self.experiment_count + iterations
        self.stop_requested = False
        threading.Thread(target=self.run_loop, daemon=True).start()

    def notify_telegram(self, message):
        # Add this line to mirror the outgoing message to the Web UI
        self.log(f"📲 **Telegram Notification Sent:**\n> {message.replace('\n', '\n> ')}")

        token = os.getenv("TELEGRAM_TOKEN")
        chat_id = os.getenv("AUTHORIZED_CHAT_ID")
        url = f"https://api.telegram.org/bot{token}/sendMessage"

        try:

            response = requests.post(url, json={"chat_id": chat_id, "text": message})
            response.raise_for_status()
        except Exception as e:
            self.log(f"⚠️ Failed to send Telegram message: {e}")

    def chat_only(self, user_text):
        """Asks a question, allowing internet search ONLY if a link is provided."""
        self.status = "Thinking..."
        self.log(f"👤 User Question: {user_text}")
        self.messages.append({"role": "user", "content": user_text})

        memory_file = os.path.join(self.work_dir, "experiment_memory.txt")
        memory_content = "No experiments recorded yet."
        if os.path.exists(memory_file):
            with open(memory_file, "r", encoding="utf-8") as f:
                memory_content = f.read()

        has_link = "http://" in user_text or "https://" in user_text or "www." in user_text

        system_instruction = "Respond directly to the user's query."
        tools_to_use = None

        if has_link:
            system_instruction += " The user provided a link. You MUST use the '$web_search' tool to read its contents before answering."
            tools_to_use = [t for t in self.tools if t["function"]["name"] == "$web_search"]
        else:
            system_instruction += " DO NOT attempt to use tools or write code."

        temp_messages = self.messages + [
            {"role": "system",
             "content": f"{system_instruction} Here is your memory:\n\n{memory_content}"}
        ]

        try:
            kwargs = {
                "model": "kimi-k2.5",
                "messages": temp_messages,
                "temperature": 0.7
            }
            if tools_to_use:
                kwargs["tools"] = tools_to_use
                kwargs["tool_choice"] = "auto"

            response = self.client.chat.completions.create(**kwargs)

            if response.usage:
                self.input_tokens += response.usage.prompt_tokens
                self.output_tokens += response.usage.completion_tokens

            msg = response.choices[0].message

            if msg.tool_calls:
                self.log("🌐 Agent is scraping the provided link...")
                temp_messages.append(msg.model_dump(exclude_none=True))

                for tool_call in msg.tool_calls:
                    if tool_call.function.name == "$web_search":
                        self.log("🌐 Triggering Moonshot's built-in web search...")
                        # Kimi's built-in search handles execution server-side.
                        # It simply expects the client to echo the arguments back in the tool message.
                        temp_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.function.name,
                            "content": tool_call.function.arguments
                        })

                response = self.client.chat.completions.create(
                    model="kimi-k2.5",
                    messages=temp_messages,
                    temperature=0.7
                )

                if response.usage:
                    self.input_tokens += response.usage.prompt_tokens
                    self.output_tokens += response.usage.completion_tokens

                msg = response.choices[0].message

            self.messages.append(msg.model_dump(exclude_none=True))

            if msg.content:
                self.log(f"🗣️ Agent: {msg.content}")
                self.notify_telegram(f"🗣️ Job {self.job_id} ({self.comp_name}) says:\n\n{msg.content}")

        except Exception as e:
            self.log(f"⚠️ Error during chat: {e}")

        self.status = "Waiting for User"

    def list_files(self):
        try:
            files = os.listdir(self.working_dir)
            return f"Files in working directory: {', '.join(files)}"
        except Exception as e:
            return f"Failed to list files: {e}"

    def write_file(self, filename, code):
        filepath = os.path.join(self.working_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(code)
        self.log(f"📝 Wrote {len(code.splitlines())} lines to {filename}.")
        return f"Successfully wrote to {filename}."

    def read_file(self, filename):
        filepath = os.path.join(self.working_dir, filename)
        if not os.path.exists(filepath):
            return f"Error: File {filename} does not exist."
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        # Add truncation to prevent token overflow
        if len(content) > 3000:
            content = content[:1500] + "\n\n... [FILE TRUNCATED FOR LENGTH] ...\n\n" + content[-1500:]

        return f"--- Contents of {filename} ---\n{content}"

    def execute_script(self, filename):
        filepath = os.path.join(self.working_dir, filename)
        if not os.path.exists(filepath):
            return f"Error: Cannot execute {filename} because it does not exist."

        self._auto_commit(f"Auto-commit before running {filename}")

        self.log(f"⚙️ Executing {filename} ...")
        result = subprocess.run(["python", filename], capture_output=True, text=True, cwd=self.working_dir)

        output = f"--- RESULTS FOR {filename} ---\n"
        if result.returncode != 0:
            output += f"ERROR:\n{result.stderr}"
            self.log(f"⚠️ {filename} crashed.")
        else:
            output += result.stdout
            self.log(f"✅ {filename} succeeded.")

        if len(output) > 2000:
            output = output[:500] + "\n... [OUTPUT TRUNCATED] ...\n" + output[-1400:]

        return output

    def revert_workspace(self):
        subprocess.run(["git", "reset", "--hard"], cwd=self.working_dir, capture_output=True)
        subprocess.run(["git", "clean", "-fd"], cwd=self.working_dir, capture_output=True)
        self.log("⏪ Workspace reverted to last functional commit.")
        return "Workspace reverted successfully. All broken changes have been undone."