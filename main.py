from fastapi import FastAPI, HTTPException, Response
import subprocess
import os
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional
import requests
import markdown2
from bs4 import BeautifulSoup
import openai
from PIL import Image
from fastapi.middleware.cors import CORSMiddleware
import httpx
import os
from typing import Dict, Any
from dateutil import parser
import sys
import logging
import re
import base64
from PIL import Image
from io import BytesIO
#import easyocr
import numpy as np

app = FastAPI()

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

ROOT_DIR: str = app.root_path
DATA_DIR: str = f"{ROOT_DIR}/data"

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

DEV_EMAIL: str = "hariharan.chandran@straive.com"

# AI Proxy
AI_URL: str = "https://api.openai.com/v1"
AIPROXY_TOKEN: str = os.environ.get("AIPROXY_TOKEN")
AI_MODEL: str = "gpt-4o-mini"
AI_EMBEDDINGS_MODEL: str = "text-embedding-3-small"

# for debugging use LLM token
if not AIPROXY_TOKEN:
    AI_URL = "https://llmfoundry.straive.com/openai/v1"
    AIPROXY_TOKEN = os.environ.get("LLM_TOKEN")

if not AIPROXY_TOKEN:
    raise KeyError("AIPROXY_TOKEN environment variables is missing")

APP_ID = "Smriti-tds-project"

@app.post("/run")
def run_task(task: str):
    if not task:
        raise HTTPException(status_code=400, detail="Task description is required")

    try:
        tool = get_task_tool(task, task_tools)
        return execute_tool_calls(tool)

    except Exception as e:
        detail: str = e.detail if hasattr(e, "detail") else str(e)

        raise HTTPException(status_code=500, detail=detail)


def execute_tool_calls(tool: Dict[str, Any]) -> Any:
    if "tool_calls" in tool:
        for tool_call in tool["tool_calls"]:
            function_name = tool_call["function"].get("name")
            function_args = tool_call["function"].get("arguments")

            # Ensure the function name is valid and callable
            if function_name in globals() and callable(globals()[function_name]):
                function_chosen = globals()[function_name]
                function_args = parse_function_args(function_args)

                if isinstance(function_args, dict):
                    return function_chosen(**function_args)

    raise HTTPException(status_code=400, detail="Unknown task")


def parse_function_args(function_args: Optional[Any]) -> Dict[str, Any]:
    if function_args is not None:
        if isinstance(function_args, str):
            function_args = json.loads(function_args)

        elif not isinstance(function_args, dict):
            function_args = {"args": function_args}
    else:
        function_args = {}

    return function_args


@app.get("/read")
def read_file(path: str) -> Response:
    if not path:
        raise HTTPException(status_code=400, detail="File path is required")

    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")

    try:
        with open(path, "r") as f:
            content = f.read()
        return Response(content=content, media_type="text/plain")

    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")


task_tools = [
    {
        "type": "function",
        "function": {
            "name": "format_file",
            "description": "Format a file using prettier",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "File path to format.",
                    }
                },
                "required": ["source"],
                "additionalProperties": False,
            },
            # "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "count_weekday",
            "description": "Count the occurrences of a specific weekday in the provided file",
            "parameters": {
                "type": "object",
                "properties": {
                    "weekday": {
                        "type": "string",
                        "description": "Day of the week (in English)",
                    },
                    "source": {
                        "type": ["string", "null"],
                        "description": "Path to the source file. If unavailable, set to null.",
                        "nullable": True,
                    },
                    "destination": {
                        "type": ["string", "null"],
                        "description": "Path to the destination file. If unavailable, set to null.",
                        "nullable": True,
                    },
                },
                "required": ["weekday", "source", "destination"],
                "additionalProperties": False,
            },
            # "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sort_contacts",
            "description": "Sort an array of contacts by first or last name",
            "parameters": {
                "type": "object",
                "properties": {
                    "order": {
                        "type": "string",
                        "description": "Sorting order, based on name",
                        "enum": ["last_name", "first_name"],
                        "default": "last_name",
                    },
                    "source": {
                        "type": ["string", "null"],
                        "description": "Path to the source file. If unavailable, set to null.",
                        "nullable": True,
                    },
                    "destination": {
                        "type": ["string", "null"],
                        "description": "Path to the destination file. If unavailable, set to null.",
                        "nullable": True,
                    },
                },
                "required": ["order", "source", "destination"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_recent_logs",
            "description": "Write the first line of the **10** most recent `.log` files in the directory `/data/logs/`, most recent first",
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {
                        "type": "integer",
                        "description": "Number of records to be listed",
                    },
                    "source": {
                        "type": ["string", "null"],
                        "description": "Path to the directory containing log files. If unavailable, set to null.",
                        "nullable": True,
                    },
                    "destination": {
                        "type": ["string", "null"],
                        "description": "Path to the destination file. If unavailable, set to null.",
                        "nullable": True,
                    },
                },
                "required": ["count", "source", "destination"],
                "additionalProperties": False,
            },
            # "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_markdown_titles",
            "description": "Index Markdown (.md) files in the directory `/data/docs/` and extract their titles",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": ["string", "null"],
                        "description": "Path to the directory containing Markdown files. If unavailable, set to null.",
                        "nullable": True,
                    },
                    "destination": {
                        "type": ["string", "null"],
                        "description": "Path to the destination file. If unavailable, set to null.",
                        "nullable": True,
                    },
                },
                "required": ["source", "destination"],
                "additionalProperties": False,
            },
            # "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_email_sender",
            "description": "Extract the **sender's** email address in an email message from `/data/email.txt`",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": ["string", "null"],
                        "description": "Path to the source file. If unavailable, set to null.",
                        "nullable": True,
                    },
                    "destination": {
                        "type": ["string", "null"],
                        "description": "Path to the destination file. If unavailable, set to null.",
                        "nullable": True,
                    },
                },
                "required": ["source", "destination"],
                "additionalProperties": False,
            },
            # "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_credit_card_number",
            "description": "Extract the 16 digit code from the image",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": ["string", "null"],
                        "description": "Path to the source image file. If unavailable, set to null.",
                        "nullable": True,
                    },
                    "destination": {
                        "type": ["string", "null"],
                        "description": "Path to the destination file. If unavailable, set to null.",
                        "nullable": True,
                    },
                },
                "required": ["source", "destination"],
                "additionalProperties": False,
            },
            # "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "similar_comments",
            "description": "Find the most similar pair of comments",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": ["string", "null"],
                        "description": "Path to the source file. If unavailable, set to null.",
                        "nullable": True,
                    },
                    "destination": {
                        "type": ["string", "null"],
                        "description": "Path to the destination file. If unavailable, set to null.",
                        "nullable": True,
                    },
                },
                "required": ["source", "destination"],
                "additionalProperties": False,
            },
            # "strict": True,
        },
    },
]


def get_task_tool(task: str, tools: list[Dict[str, Any]]) -> Dict[str, Any]:
    response = httpx.post(
        f"{AI_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {AIPROXY_TOKEN}:{APP_ID}",
            "Content-Type": "application/json",
        },
        json={
            "model": AI_MODEL,
            "messages": [{"role": "user", "content": task}],
            "tools": tools,
            "tool_choice": "auto",
        },
    )

    json_response = response.json()

    if "error" in json_response:
        raise HTTPException(status_code=500, detail=json_response["error"]["message"])

    return json_response["choices"][0]["message"]


def get_chat_completions(messages: list[Dict[str, Any]]) -> Dict[str, Any]:
    response = httpx.post(
        f"{AI_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {AIPROXY_TOKEN}:{APP_ID}",
            "Content-Type": "application/json",
        },
        json={
            "model": AI_MODEL,
            "messages": messages,
        },
    )

    # response.raise_for_status()

    json_response = response.json()

    if "error" in json_response:
        raise HTTPException(status_code=500, detail=json_response["error"]["message"])

    return json_response["choices"][0]["message"]


def get_embeddings(text: str) -> Dict[str, Any]:
    response = httpx.post(
        f"{AI_URL}/embeddings",
        headers={
            "Authorization": f"Bearer {AIPROXY_TOKEN}:{APP_ID}",
            "Content-Type": "application/json",
        },
        json={
            "model": AI_EMBEDDINGS_MODEL,
            "input": text,
        },
    )

    # response.raise_for_status()

    json_response = response.json()

    if "error" in json_response:
        raise HTTPException(status_code=500, detail=json_response["error"]["message"])

    return json_response["data"][0]["embedding"]


def file_rename(name: str, suffix: str) -> str:
    return (re.sub(r"\.(\w+)$", "", name) + suffix).lower()


# A1. Data initialization
def initialize_data():
    logging.info(f"DATA - {DATA_DIR}")
    logging.info(f"USER - {DEV_EMAIL}")

    try:
        # Ensure the 'uv' package is installed
        try:
            import uv

        except ImportError:
            logging.info("'uv' package not found. Installing...")

            subprocess.check_call([sys.executable, "-m", "ensurepip", "--upgrade"])

            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "--upgrade", "uv"]
            )

            import uv

        # Run the data generation script
        result = subprocess.run(
            [
                "uv",
                "run",
                "https://raw.githubusercontent.com/sanand0/tools-in-data-science-public/tds-2025-01/project-1/datagen.py",
                f"--root={DATA_DIR}",
                DEV_EMAIL,
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            logging.info("Data initialization completed successfully.")

        else:
            logging.error(
                f"Data initialization failed with return code {result.returncode}"
            )
            logging.error(f"Error output: {result.stderr}")

    except subprocess.CalledProcessError as e:
        logging.error(f"Subprocess error: {e}")
        logging.error(f"Output: {e.output}")

    except Exception as e:
        logging.error(f"Error in initializing data: {e}")


# A2. Format a file using prettier
import os
import subprocess
from fastapi import HTTPException

def format_file(source: str = None) -> dict:
    if not source:
        raise HTTPException(status_code=400, detail="Source file is required")

    file_path = os.path.abspath(source)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    try:
        # Step 1: Run Prettier with improved options
        prettier_cmd = [
            "npx", "prettier", "--write",
            "--parser", "markdown",
            "--prose-wrap", "preserve",  # Prevents unwanted line breaks
            "--tab-width", "2",
            "--use-tabs", "false",
            "--no-semi",  # Helps with bullet list issues
            file_path
        ]

        prettier_result = subprocess.run(
            prettier_cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if prettier_result.stderr:
            raise HTTPException(status_code=500, detail=prettier_result.stderr.strip())

        # Step 2: Verify Formatting & Fallback to remark-cli if needed
        with open(file_path, "r", encoding="utf-8") as f:
            formatted_content = f.read()

        # Check if formatting is incorrect (example heuristic)
        if "  +" in formatted_content or formatted_content.count("\n") < 3:
            # Fallback to remark-cli if Prettier messed up the structure
            remark_cmd = ["npx", "remark", "--output", file_path]
            subprocess.run(remark_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        return {"message": "File formatted successfully", "file": file_path, "status": "success"}

    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"Formatting Error: {e.stderr}")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


# A3. Count the number of week-days in the list of dates
day_names = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


def count_weekday(weekday: str, source: str = None, destination: str = None) -> dict:
    weekday = normalize_weekday(weekday)
    weekday_index = day_names.index(weekday)

    if not source:
        raise HTTPException(status_code=400, detail="Source file is required")

    file_path: str = source
    output_path: str = destination or file_rename(file_path, f"-{weekday}.txt")

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    with open(file_path, "r") as f:
        dates = [parser.parse(line.strip()) for line in f if line.strip()]

    day_count = sum(1 for d in dates if d.weekday() == weekday_index)

    with open(output_path, "w") as f:
        f.write(str(day_count))

    return {
        "message": f"{weekday} counted",
        "count": day_count,
        "source": file_path,
        "destination": output_path,
        "status": "success",
    }


def normalize_weekday(weekday):
    if isinstance(weekday, int):  # If input is an integer (0-6)
        return day_names[weekday % 7]

    elif isinstance(weekday, str):  # If input is a string
        weekday = weekday.strip().lower()
        days = {day.lower(): day for day in day_names}
        short_days = {day[:3].lower(): day for day in day_names}

        if weekday in days:
            return days[weekday]

        elif weekday in short_days:
            return short_days[weekday]

    raise ValueError("Invalid weekday input")


# A4. Sort the array of contacts by last name and first name
import json

def sort_contacts(order: str, source: Optional[str], destination: Optional[str]):
    logger.info(f"Sorting contacts from {source}, order: {order}, writing to {destination}")

    if not source or not os.path.exists(source):
        raise HTTPException(status_code=400, detail="Source file not found")

    if not destination:
        raise HTTPException(status_code=400, detail="Destination file not provided")

    try:
        with open(source, "r") as f:
            contacts = json.load(f)

        key = "last_name" if order == "last_name" else "first_name"
        sorted_contacts = sorted(contacts, key=lambda x: x.get(key, "").lower())

        with open(destination, "w") as f:
            json.dump(sorted_contacts, f, indent=4)

        logger.info(f"Sorted contacts written successfully to {destination}")
        return {"message": "Contacts sorted successfully"}

    except Exception as e:
        logger.error(f"Error sorting contacts: {str(e)}")
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")

# A5. Write the first line of the 10 most recent .log file in /data/logs/ to /data/logs-recent.txt, most recent first
def write_recent_logs(count: int, source: str = None, destination: str = None):
    if count < 1:
        raise HTTPException(status_code=400, detail="Invalid count")

    if not source:
        raise HTTPException(status_code=400, detail="Source file is required")

    file_path: str = source
    file_dir: str = os.path.dirname(file_path)
    output_path: str = destination or os.path.join(DATA_DIR, f"{file_dir}-recent.txt")

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    log_files = sorted(
        [
            os.path.join(file_path, f)
            for f in os.listdir(file_path)
            if f.endswith(".log")
        ],
        key=os.path.getmtime,
        reverse=True,
    )

    with open(output_path, "w") as out:
        for log_file in log_files[:count]:
            with open(log_file, "r") as f:
                first_line = f.readline().strip()
                out.write(f"{first_line}\n")

    return {
        "message": "Recent logs written",
        "log_dir": file_path,
        "output_file": output_path,
        "status": "success",
    }


# A6. Index for Markdown (.md) files in /data/docs/
def extract_markdown_titles(source: str = None, destination: str = None):
    if not source:
        raise HTTPException(status_code=400, detail="Source file is required")

    file_path: str = source
    output_path: str = destination or os.path.join(file_path, "index.json")

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Directory not found")

    index = {}
    collect_markdown_titles(file_path, index)

    with open(output_path, "w") as f:
        json.dump(index, f, indent=4)

    return {
        "message": "Markdown titles extracted",
        "file_dir": file_path,
        "index_file": output_path,
        "status": "success",
    }


def collect_markdown_titles(directory: str, index: dict):
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".md"):
                file_path = os.path.join(root, file)
                with open(file_path, "r") as f:
                    title = None
                    for line in f:
                        if line.startswith("# "):
                            title = line[2:].strip()
                            break

                    if title:
                        relative_path = os.path.relpath(file_path, directory)
                        relative_path = re.sub(r"[\\/]+", "/", relative_path)
                        index[relative_path] = title


# A7. Extract the sender's email address from an email message
def extract_email_sender(source: str = None, destination: str = None):
    if not source:
        raise HTTPException(status_code=400, detail="Source file is required")

    file_path: str = source
    output_path: str = destination or file_rename(file_path, "-sender.txt")

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    with open(file_path, "r") as f:
        email_content = f.read()

    response = get_chat_completions(
        [
            {"role": "system", "content": "Extract the sender's email."},
            {"role": "user", "content": email_content},
        ]
    )

    extracted_email = response["content"].strip()

    with open(output_path, "w") as f:
        f.write(extracted_email)

    return {
        "message": "Email extracted",
        "source": file_path,
        "destination": output_path,
        "status": "success",
    }


# A8. Extract credit card number.
def encode_image(image_path: str, format: str):
    image = Image.open(image_path)

    buffer = BytesIO()
    image.save(buffer, format=format)
    image_bytes = buffer.getvalue()

    base64_image = base64.b64encode(image_bytes).decode("utf-8")

    return base64_image


def extract_credit_card_number(source: str = None, destination: str = None):
    if not source:
        raise HTTPException(status_code=400, detail="Source file is required")

    file_path: str = source
    output_path: str = destination or file_rename(file_path, "-number.txt")

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Image file not found")
    import easyocr
    # Taking more time
    reader = easyocr.Reader(["en"])
    results = reader.readtext(file_path, detail=0)

    extracted_text = "\n".join(results)
    extracted_text = re.sub(r"[- ]+", "", extracted_text)
    matches = re.findall(
        r"\b(?:4\d{12}(?:\d{3})?|5[1-5]\d{14}|3[47]\d{13}|6(?:011|5\d{2})\d{12}|3(?:0[0-5]|[68]\d)\d{11}|(?:2131|1800|35\d{3})\d{11})\b",
        extracted_text,
    )

    extracted_number = (
        matches[0] if (matches and len(matches) > 0) else "No credit card number found"
    )

    ## hard to install pytesseract
    # image = Image.open(file_path)
    # extracted_text = pytesseract.image_to_string(image)

    ## below not working because of sensity data
    # base64_image = encode_image(file_path, "PNG")
    # image_url = f"data:image/png;base64,{base64_image}"
    #
    # response = get_chat_completions(
    #     [
    #         {
    #             "role": "system",
    #             "content": "Extract the credit card number from the image.",
    #         },
    #         {
    #             "role": "user",
    #             "content": [{"type": "image_url", "image_url": {"url": image_url}}],
    #         },
    #     ]
    # )
    #
    # extracted_number = response["content"].strip()

    with open(output_path, "w") as f:
        f.write(extracted_number)

    return {
        "message": "Credit card number extracted",
        "source": file_path,
        "destination": output_path,
        "status": "success",
    }


# A9. Simillar Comments
def cosine_similarity(vec1, vec2):
    return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))


def similar_comments(source: str = None, destination: str = None):
    if not source:
        raise HTTPException(status_code=400, detail="Source file is required")

    file_path: str = source
    output_path: str = destination or file_rename(file_path, "-similar.txt")

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    # Load comments
    with open(file_path, "r", encoding="utf-8") as f:
        comments = [line.strip() for line in f.readlines()]

    # Compute embeddings
    embeddings = [get_embeddings(comment) for comment in comments]

    # Find the most similar pair
    max_sim = -1
    most_similar_pair = (None, None)

    for i in range(len(comments)):
        for j in range(i + 1, len(comments)):
            sim = cosine_similarity(embeddings[i], embeddings[j])
            if sim > max_sim:
                max_sim = sim
                most_similar_pair = (comments[i], comments[j])

    # Write the most similar pair to output file
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(most_similar_pair))

    return {
        "message": "Similar comments extracted",
        "source": file_path,
        "destination": output_path,
        "status": "success",
    }


# A10
def calculate_ticket_sales(task):
    db_path = os.path.join(DATA_DIR, "ticket-sales.db")
    output_path = os.path.join(DATA_DIR, "ticket-sales-gold.txt")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT SUM(units * price) FROM tickets WHERE type = 'Gold'")
    total_sales = cursor.fetchone()[0] or 0

    conn.close()

    with open(output_path, "w") as f:
        f.write(str(total_sales))

    return {
        "message": "Sales calculated",
        "total_sales": total_sales,
        "status": "success",
    }


# Installion of data is done through Dockerfile
# initialize_data()