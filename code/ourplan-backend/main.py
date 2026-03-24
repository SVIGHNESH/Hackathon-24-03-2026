import os
import json
import asyncio
import uuid
import smtplib
from datetime import datetime
from typing import Optional
from email.message import EmailMessage
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

load_dotenv()

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.5-flash")

try:
    from google import genai
    genai_client = genai.Client(api_key=LLM_API_KEY)
    USE_GENAI_SDK = bool(LLM_API_KEY)
except Exception:
    genai_client = None
    USE_GENAI_SDK = False

app = FastAPI(title="Neurax API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Task(BaseModel):
    id: str
    title: str
    description: str
    requiredSkills: list[str]
    estimatedHours: int

class Employee(BaseModel):
    id: str
    name: str
    role: str
    skills: list[str]
    experience: str
    email: Optional[str] = ""

class TaskAssignment(BaseModel):
    taskId: str
    taskTitle: str
    employeeId: str
    employeeName: str
    matchScore: int

class CrewConfig(BaseModel):
    name: str
    tasks: list[TaskAssignment]
    generatedAt: str

class ParsePRDRequest(BaseModel):
    text: Optional[str] = None
    tasks: Optional[list[Task]] = None

class ParseResumeRequest(BaseModel):
    employees: Optional[list[Employee]] = None

class CrewGenerateRequest(BaseModel):
    tasks: list[Task]
    employees: list[Employee]

class CrewRunRequest(BaseModel):
    config: CrewConfig

class CrewNotifyRequest(BaseModel):
    config: CrewConfig
    employees: list[Employee]

async def call_llm(prompt: str) -> str:
    if not LLM_API_KEY:
        print("No LLM_API_KEY configured")
        return ""
    
    try:
        if USE_GENAI_SDK and genai_client:
            response = genai_client.models.generate_content(
                model=LLM_MODEL,
                contents=prompt
            )
            return response.text or ""
        return ""
    except Exception as e:
        print(f"LLM exception: {e}")
        return ""

def get_smtp_settings() -> dict:
    return {
        "host": os.getenv("SMTP_HOST", ""),
        "port": int(os.getenv("SMTP_PORT", "587")),
        "username": os.getenv("SMTP_USERNAME", ""),
        "password": os.getenv("SMTP_PASSWORD", ""),
        "from_email": os.getenv("SMTP_FROM_EMAIL", os.getenv("SMTP_USERNAME", "")),
        "use_tls": os.getenv("SMTP_USE_TLS", "true").lower() == "true",
        "use_ssl": os.getenv("SMTP_USE_SSL", "false").lower() == "true",
    }

def send_assignment_email(to_email: str, subject: str, body: str, settings: dict):
    message = EmailMessage()
    message["From"] = settings["from_email"]
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    smtp_factory = smtplib.SMTP_SSL if settings["use_ssl"] else smtplib.SMTP
    with smtp_factory(settings["host"], settings["port"], timeout=20) as smtp:
        if not settings["use_ssl"] and settings["use_tls"]:
            smtp.starttls()
        if settings["username"] and settings["password"]:
            smtp.login(settings["username"], settings["password"])
        smtp.send_message(message)

@app.get("/")
async def root():
    return {"status": "ok", "message": "Neurax API running"}

@app.post("/parse-prd")
async def parse_prd(
    text: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None)
):
    content = text or ""
    
    if file:
        content = await file.read()
        if hasattr(content, 'decode'):
            content = content.decode('utf-8', errors='ignore')
    
    if not content:
        raise HTTPException(status_code=400, detail="No content provided")
    
    print(f"Calling LLM with content length: {len(content)}")
    llm_response = await call_llm(
        f"""You are a project manager. Parse this PRD and extract actionable tasks.
For each task provide: id (number), title, description, requiredSkills (array of strings), estimatedHours (number).
Return ONLY a valid JSON array. No markdown, no explanation.

PRD:
{content[:3000]}"""
    )
    print(f"LLM response: {llm_response[:200] if llm_response else 'EMPTY'}")
    
    if llm_response:
        try:
            tasks = json.loads(llm_response)
            return {"tasks": tasks}
        except:
            pass
    
    keywords = ["api", "database", "ui", "frontend", "backend", "auth", "payment", "dashboard", "mobile", "testing"]
    tasks = []
    for kw in keywords:
        if kw.lower() in content.lower():
            tasks.append({
                "id": str(uuid.uuid4())[:8],
                "title": f"{kw.title()} Implementation",
                "description": f"Implement {kw} functionality",
                "requiredSkills": [kw.title(), "Development"],
                "estimatedHours": 8
            })
    
    if not tasks:
        tasks = [
            {"id": "1", "title": "Design System Implementation", "description": "Create reusable UI components", "requiredSkills": ["React", "TypeScript", "CSS"], "estimatedHours": 8},
            {"id": "2", "title": "Backend API Development", "description": "Build RESTful APIs", "requiredSkills": ["Python", "FastAPI", "PostgreSQL"], "estimatedHours": 12},
        ]
    
    return {"tasks": tasks}

def extract_text_from_pdf(content: bytes) -> str:
    """Extract text from PDF binary content"""
    try:
        import pdfplumber
        import io
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            text = ""
            for page in pdf.pages:
                text += page.extract_text() or ""
            return text
    except Exception as e:
        print(f"PDF extraction error: {e}")
        return content.decode('utf-8', errors='ignore')

@app.post("/parse-resume")
async def parse_resume(files: list[UploadFile] = File(None)):
    employees = []
    
    for file in files:
        content = await file.read()
        
        # Extract text from PDF if it's a PDF file
        if file.filename and file.filename.lower().endswith('.pdf'):
            content = extract_text_from_pdf(content)
        elif hasattr(content, 'decode'):
            content = content.decode('utf-8', errors='ignore')
        
        print(f"Parsing resume: {file.filename}, text length: {len(content)}")
        llm_response = await call_llm(
            f"""You are an HR specialist. Extract employee information from this resume.
Look for: name, email, job title/role, skills, years of experience.
Return ONLY a valid JSON object like: {{"name": "John Doe", "email": "john@example.com", "role": "Software Engineer", "skills": ["Python", "Java"], "experience": "5 years"}}
If cannot find a field, use empty string "" instead of null.
No markdown, no explanation, just the JSON.

Resume content:
{content[:4000]}"""
        )
        print(f"Resume LLM response: {llm_response[:500] if llm_response else 'EMPTY'}")
        
        if llm_response:
            try:
                emp = json.loads(llm_response)
                emp["id"] = str(uuid.uuid4())[:8]
                employees.append(emp)
            except:
                pass
    
    if not employees:
        employees = [
            {"id": "1", "name": "Alex Chen", "email": "alex.chen@example.com", "role": "Frontend Developer", "skills": ["React", "TypeScript", "CSS", "Node.js"], "experience": "5 years"},
            {"id": "2", "name": "Sarah Miller", "email": "sarah.miller@example.com", "role": "Backend Developer", "skills": ["Python", "FastAPI", "PostgreSQL", "Docker"], "experience": "7 years"},
            {"id": "3", "name": "James Wilson", "email": "james.wilson@example.com", "role": "Full Stack Developer", "skills": ["React", "Node.js", "Python", "SQL"], "experience": "4 years"},
        ]
    
    return {"employees": employees}

@app.post("/crew-generate")
async def crew_generate(request: CrewGenerateRequest):
    assignments = []
    employee_task_counts = {emp.id: 0 for emp in request.employees}
    
    for task in request.tasks:
        best_match = None
        best_score = 0
        
        for emp in request.employees:
            task_skills = set(s.lower() for s in task.requiredSkills)
            emp_skills = set(s.lower() for s in emp.skills)
            matches = len(task_skills & emp_skills)
            score = min(100, 50 + matches * 15)

            # If scores tie, prefer the employee with fewer assigned tasks
            current_load = employee_task_counts.get(emp.id, 0)
            best_load = employee_task_counts.get(best_match.id, 0) if best_match else float("inf")

            if score > best_score or (score == best_score and current_load < best_load):
                best_score = score
                best_match = emp
        
        if best_match:
            assignments.append({
                "taskId": task.id,
                "taskTitle": task.title,
                "employeeId": best_match.id,
                "employeeName": best_match.name,
                "matchScore": best_score
            })
            employee_task_counts[best_match.id] = employee_task_counts.get(best_match.id, 0) + 1
    
    config = {
        "name": "Project Crew",
        "tasks": assignments,
        "generatedAt": datetime.now().isoformat()
    }
    
    return {"assignments": assignments, "config": config}

async def generate_logs(config: CrewConfig):
    yield "data: " + json.dumps({"timestamp": datetime.now().isoformat(), "agent": "coordinator", "status": "started", "message": "Initializing crew execution..."}) + "\n\n"
    await asyncio.sleep(0.5)
    
    yield "data: " + json.dumps({"timestamp": datetime.now().isoformat(), "agent": "coordinator", "status": "completed", "message": "Crew initialized successfully"}) + "\n\n"
    await asyncio.sleep(0.3)
    
    seen_agents = set()
    for assignment in config.tasks:
        agent_name = f"{assignment.employeeName.split()[0]} Agent"
        if agent_name not in seen_agents:
            seen_agents.add(agent_name)
            yield "data: " + json.dumps({"timestamp": datetime.now().isoformat(), "agent": agent_name, "status": "started", "message": f"Starting task: {assignment.taskTitle}"}) + "\n\n"
            await asyncio.sleep(0.8)
            yield "data: " + json.dumps({"timestamp": datetime.now().isoformat(), "agent": agent_name, "status": "completed", "message": f"Completed: {assignment.taskTitle}"}) + "\n\n"
    
    yield "data: " + json.dumps({"timestamp": datetime.now().isoformat(), "agent": "coordinator", "status": "completed", "message": "All tasks completed successfully"}) + "\n\n"

@app.post("/crew-run-stream")
async def crew_run_stream(request: CrewRunRequest):
    return StreamingResponse(generate_logs(request.config), media_type="text/event-stream")

@app.post("/notify-assignments")
async def notify_assignments(request: CrewNotifyRequest):
    if not request.config.tasks:
        raise HTTPException(status_code=400, detail="No assignments available to notify")

    smtp_settings = get_smtp_settings()
    if not smtp_settings["host"] or not smtp_settings["from_email"]:
        raise HTTPException(
            status_code=503,
            detail="SMTP is not configured. Set SMTP_HOST and SMTP_FROM_EMAIL in backend .env",
        )

    employees_by_id = {str(emp.id): emp for emp in request.employees}
    grouped_assignments: dict[str, list[TaskAssignment]] = {}
    for assignment in request.config.tasks:
        grouped_assignments.setdefault(str(assignment.employeeId), []).append(assignment)

    sent = []
    skipped = []

    for employee_id, assignments in grouped_assignments.items():
        employee = employees_by_id.get(employee_id)
        if not employee:
            skipped.append({"employeeId": employee_id, "reason": "Employee not found in request payload"})
            continue

        recipient = (employee.email or "").strip()
        if not recipient or "@" not in recipient:
            skipped.append({"employeeId": employee_id, "employeeName": employee.name, "reason": "Missing valid email"})
            continue

        task_lines = "\n".join(
            [f"- {a.taskTitle} (match: {a.matchScore}%)" for a in assignments]
        )
        subject = f"[{request.config.name}] New Task Assignment"
        body = (
            f"Hello {employee.name},\n\n"
            f"You have been assigned the following work items:\n"
            f"{task_lines}\n\n"
            f"Generated at: {request.config.generatedAt}\n\n"
            "Please start with the highest-priority task first."
        )

        try:
            send_assignment_email(recipient, subject, body, smtp_settings)
            sent.append(
                {
                    "employeeId": employee_id,
                    "employeeName": employee.name,
                    "email": recipient,
                    "taskCount": len(assignments),
                }
            )
        except Exception as exc:
            skipped.append(
                {
                    "employeeId": employee_id,
                    "employeeName": employee.name,
                    "email": recipient,
                    "reason": f"Email send failed: {exc}",
                }
            )

    return {"sent": sent, "skipped": skipped}

@app.get("/crew-download")
async def crew_download():
    return {"message": "Download endpoint - implement file generation"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)