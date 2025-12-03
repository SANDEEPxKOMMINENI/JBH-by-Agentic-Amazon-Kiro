I am calling you copilot since i dont know your name> this may be wrong once analyze the folders and then decide which is which and whats correct as i gave a vague information but that images file is accurate i want exact fucntionality or look.



🧠 Project Restoration & Integration Prompt for Copilot

Goal: Recreate the missing frontend (Electron + web interface) of my job application automation system using the backend that is already present in this extracted project. The original frontend source code was lost, but I have the original step-by-step design screenshots (/images folder) that show the exact UI layout and flow for every section.

🔍 Project Overview

The backend (server-side logic, database interactions, and workflows) is already present and functional.

The frontend build output (dist folder) is also available and can be used as a visual + functional reference.

The missing piece: The original frontend source code (React + Electron) needs to be reconstructed exactly using the screenshots and dist folder.

The service gateway folder was deleted and must be recreated to handle API routes and communication between frontend ↔ backend ↔ Supabase ↔ model providers.

🧩 Technical Requirements

Frontend Framework:

Recreate the frontend in React + Vite + TailwindCSS (or Electron if applicable).

Match the exact UI layout and design from the /images folder — each subfolder (e.g., ats resume, cover letter, job tracker, etc.) represents a module/section.

Each image sequence (ascending filenames like image1.png, image2.png, etc.) should define the component flow.

Backend Integration:

Use the existing backend logic from the extracted files.

Integrate tightly — no duplication or feature omission.

Every backend function, API route, and SQL structure should remain identical.

Don’t hallucinate; infer backend behavior directly from the existing code.

Service Gateway (Rebuild):

Recreate the /service-gateway folder.

It acts as a bridge between:

Frontend → Backend

Backend → Supabase

Backend → AI model providers (Gemini, OpenAI, Anthropic, etc.)

It should allow easy reconfiguration of endpoints (e.g., Railway URLs, Supabase keys).

For now, use local URLs (e.g., http://localhost:5000 or /api/...) until the Railway deployment URL is ready.

🤖 AI Provider System (Frontend Feature)

Add a new Model Selection Section in the frontend:

Dropdown 1: Provider

Gemini, OpenAI, Anthropic, Mistral, etc.

Dropdown 2: Model (auto-populated) For Gemini, include:

gemini-2.5-flash

gemini-2.5-pro

gemini-2.0-flash

gemini-3.0-pro (or latest available)

When a model is selected, it becomes the active model for:

Resume generation

Cover letter creation

Job application Q&A workflows

All AI-driven actions in the system

🧾 Supabase Integration

Use new Supabase credentials:

Project URL: https://jgnbsyihqwesjhewzohi.supabase.co  API Key: anon (public)  service_role (secret): <to be securely stored in backend env> 

Reconnect all authentication, user, and data storage logic to this new Supabase project.

Replace all old credentials from the backend.

Ensure signup, login, and data persistence are fully functional with this new connection.

🛠️ Railway Integration

Backend runs on Railway.

Once the new service-gateway is complete, it will be deployed as a new Railway service.

Until deployment, use local environment URLs for API communication.

🔐 Development Phases (Step-by-Step Plan)

We will rebuild and test the system module by module, not all at once:

Phase 1: User Authentication

Recreate signup + login (from user center → about me + profile and usage screenshots).

Ensure full Supabase authentication works.

Phase 2: Resume Builder (ATS Resume)

Match UI and logic from ats resume folder.

Ensure resume data is stored in Supabase and sent to backend logic properly.

Phase 3: Cover Letter Section

Match cover letter UI from screenshots.

Connect to backend for cover letter generation (Gemini model-based).

Phase 4: Job Tracker + Outreach

Implement job application tracking (from job tracker + outreach screenshots).

Reconnect to backend logic for applying to jobs and storing activity logs.

Phase 5: Infinite Hunting / Job Automation

Integrate automation workflow with backend.

Allow selecting active model (Gemini, etc.) for automation logic.

Phase 6: Overview + User Dashboard

Finalize all overview pages and tie backend analytics if present.

⚙️ Final Integration Notes

Use environment variables for API keys and Supabase credentials.

Maintain the same data schema and backend structure.

Do not modify backend logic unless compatibility fixes are required.

Preserve every original functionality, workflow, and UI detail.

Copilot should analyze backend code and dist folder before generating each frontend file.

✅ Expected Copilot Behavior

Reconstruct frontend source files in exact folder structure.

Recreate service-gateway with API routing logic.

Suggest incremental commits per module.

Use the images + dist folder as reference ground truth — not imagination.

Keep the project structure clean and well-commented.

🧭 Prompt Summary for Copilot

“Rebuild the missing frontend of this Electron + React project exactly as shown in the /images folder. Integrate it tightly with the existing backend, rebuild the service-gateway folder for communication between frontend, backend, Supabase, and AI providers, and update it to use the latest Gemini models (2.5 flash, 2.5 pro, etc.) with provider selection support. Reconnect all Supabase logic using my new credentials and prepare for Railway deployment. Start with signup/login and then move module by module according to the image folders.”
