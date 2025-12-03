# Requirements Document

## Introduction

This document specifies the requirements for rebuilding the JobHuntr frontend application - an Electron-based desktop application that provides a comprehensive job application automation system. The frontend was lost but must be recreated exactly based on existing screenshots, the dist folder output, and the existing Python FastAPI backend. The system integrates with multiple job platforms (LinkedIn, Indeed, Glassdoor, Dice, ZipRecruiter), uses AI models for resume optimization and cover letter generation, and provides automated job application workflows. before doing this i want you to push the entire code to https://github.com/SANDEEPxKOMMINENI/JBH-by-Agentic-Amazon-Kiro.git
and then proceed with the following steps

## Glossary

- **JobHuntr**: The complete job application automation system
- **Frontend**: The Electron + React + Vite + TailwindCSS user interface application
- **Backend**: The existing Python FastAPI server that handles bot automation and business logic and all you are required to deeply analysis the backend everytime you are making something and make sure the sql code that is to be run in the sql editor in the supabase is exactly the same etc so that no flow will be distrupted
- **Service Gateway**: A middleware layer that routes API requests between frontend, backend, Supabase, and AI providers
- **Supabase**: The authentication and database service (PostgreSQL-based)
- **Infinite Hunt**: An automated job hunting mode that continuously searches and applies to jobs across multiple platforms
- **Workflow Run**: A single execution instance of a job hunting or searching task
- **Agent Run Template**: A predefined workflow configuration (e.g., "linkedin-apply", "indeed-search")
- **ATS Resume**: Applicant Tracking System optimized resume templates
- **AI Provider**: External AI model services (Gemini, OpenAI, Anthropic only the ones already existed in the backend and ollama too if it exists)
- **Bot Controller**: Backend component that manages platform-specific automation (LinkedIn bot, Indeed bot, etc.)

## Requirements

### Requirement 1: User Authentication and Profile Management

**User Story:** As a user, I want to sign up, log in, and manage my profile, so that I can securely access the job hunting platform and maintain my personal information.

#### Acceptance Criteria

1. WHEN a user visits the application for the first time, THE Frontend SHALL display a signup interface with email and password fields
2. WHEN a user submits valid signup credentials, THE Frontend SHALL authenticate with Supabase and create a new user account
3. WHEN a user logs in with valid credentials, THE Frontend SHALL retrieve and store a JWT authentication token
4. WHEN a user accesses the user center, THE Frontend SHALL display profile information including usage statistics
5. WHEN a user updates their "About Me" information, THE Frontend SHALL persist the changes to Supabase

### Requirement 2: ATS Resume Template Management

**User Story:** As a user, I want to create, edit, and manage ATS-optimized resume templates, so that I can tailor my resume for different job applications.

#### Acceptance Criteria

1. WHEN a user navigates to the ATS Resume section, THE Frontend SHALL display a list of existing resume templates
2. WHEN a user clicks "Create New Template", THE Frontend SHALL initiate a multi-step wizard starting with file upload
3. WHEN a user uploads a resume file in step 1, THE Frontend SHALL send the file to the Backend for processing
4. WHEN a user edits resume content in step 2, THE Frontend SHALL provide a rich text editor interface
5. WHEN a user adds additional experience in step 3, THE Frontend SHALL allow adding multiple experience entries
6. WHEN a user clicks "Test" in step 4, THE Frontend SHALL send the resume to an AI provider for ATS optimization analysis
7. WHEN the AI analysis completes in step 5, THE Frontend SHALL display three sections: preview, analysis, and code with diff highlighting
8. WHEN a user completes the template, THE Frontend SHALL save it to Supabase and display it in the templates list

### Requirement 3: Cover Letter Generation

**User Story:** As a user, I want to generate customized cover letters for specific job postings, so that I can improve my application quality.

#### Acceptance Criteria

1. WHEN a user navigates to the Cover Letter section, THE Frontend SHALL display existing cover letter templates
2. WHEN a user creates a new cover letter, THE Frontend SHALL guide them through a 4-step process
3. WHEN a user selects a template in step 1, THE Frontend SHALL load the template structure
4. WHEN a user edits the template in step 2, THE Frontend SHALL provide a rich text editor
5. WHEN a user selects a resume in step 3, THE Frontend SHALL load resume data for context
6. WHEN a user provides job information in step 4, THE Frontend SHALL send all data to the Backend with the selected AI model
7. WHEN the Backend returns the generated cover letter, THE Frontend SHALL display it with preview and download options

### Requirement 4: Job Tracker and Application History

**User Story:** As a user, I want to view and manage my job applications, so that I can track my application status and history.

#### Acceptance Criteria

1. WHEN a user navigates to the Job Tracker section, THE Frontend SHALL display a list of all job applications
2. WHEN a user clicks on a job entry, THE Frontend SHALL display detailed information including company, position, status, and application date
3. WHEN the Backend updates application status, THE Frontend SHALL reflect the changes in real-time
4. WHEN a user filters or searches jobs, THE Frontend SHALL update the displayed list accordingly

### Requirement 5: Workflow Run Management (All Runs)

**User Story:** As a user, I want to create and manage job hunting workflow runs, so that I can automate my job search across multiple platforms.

#### Acceptance Criteria

1. WHEN a user navigates to All Runs section, THE Frontend SHALL display a list of all workflow runs with their status
2. WHEN a user clicks "New Run", THE Frontend SHALL display a platform selection interface
3. WHEN a user selects a platform and proceeds, THE Frontend SHALL display a multi-step setup wizard
4. WHEN a user configures search parameters in the setup wizard, THE Frontend SHALL validate and store the configuration
5. WHEN a user clicks "Start Job Hunting", THE Frontend SHALL send a start request to the Backend with the workflow configuration
6. WHEN a workflow run starts, THE Frontend SHALL display an activity log showing real-time progress
7. WHEN the Backend emits activity updates, THE Frontend SHALL append them to the activity log display

### Requirement 6: Infinite Hunt Automation

**User Story:** As a user, I want to enable continuous automated job hunting, so that the system can search and apply to jobs without manual intervention.

#### Acceptance Criteria

1. WHEN a user navigates to the Infinite Hunting section, THE Frontend SHALL display the current infinite hunt status
2. WHEN a user clicks "Start Infinite Hunt", THE Frontend SHALL send a start request to the Backend endpoint `/api/infinite-hunt/start`
3. WHEN infinite hunt is running, THE Frontend SHALL display real-time metadata including active agent run, job stats, and duration
4. WHEN a user clicks "Pause", THE Frontend SHALL send a pause request to `/api/infinite-hunt/pause`
5. WHEN a user clicks "Resume", THE Frontend SHALL send a resume request to `/api/infinite-hunt/resume`
6. WHEN a user clicks "Stop", THE Frontend SHALL send a stop request to `/api/infinite-hunt/stop` and update the UI to idle state
7. WHEN the Backend updates job statistics, THE Frontend SHALL display queued, skipped, submitted, and failed counts

### Requirement 7: AI Model Provider Selection

**User Story:** As a user, I want to select which AI model provider and specific model to use, so that I can control the AI service used for resume optimization and cover letter generation.

#### Acceptance Criteria

1. WHEN a user accesses AI-dependent features, THE Frontend SHALL display a model selection interface
2. WHEN a user selects a provider from the dropdown, THE Frontend SHALL populate the model dropdown with available models for that provider
3. WHEN Gemini is selected as provider, THE Frontend SHALL display models including gemini-2.5-flash, gemini-2.5-pro, gemini-2.0-flash
4. WHEN a user selects a specific model, THE Frontend SHALL store this selection as the active model for all AI operations
5. WHEN the Frontend sends requests to the Backend for AI operations, THE Frontend SHALL include the selected model identifier in the request payload

### Requirement 8: Service Gateway API Routing

**User Story:** As a system architect, I want a service gateway layer, so that API communication between frontend, backend, Supabase, and AI providers is properly routed and managed.

#### Acceptance Criteria

1. WHEN the Frontend makes an API request, THE Service Gateway SHALL route it to the appropriate backend endpoint
2. WHEN the Backend needs to access Supabase, THE Service Gateway SHALL include proper authentication headers
3. WHEN the Backend needs to call AI providers, THE Service Gateway SHALL route requests with appropriate API keys
4. WHEN environment variables change, THE Service Gateway SHALL allow reconfiguration without code changes
5. WHEN deployed to Railway, THE Service Gateway SHALL use production URLs instead of localhost

### Requirement 9: Real-time Activity Monitoring

**User Story:** As a user, I want to see real-time updates of bot activities, so that I can monitor what the automation is doing.

#### Acceptance Criteria

1. WHEN a workflow run is active, THE Frontend SHALL poll the Backend for activity updates at regular intervals
2. WHEN the Backend returns new activity logs, THE Frontend SHALL append them to the activity display
3. WHEN an activity log contains status information, THE Frontend SHALL display it with appropriate formatting and icons
4. WHEN a workflow run completes or fails, THE Frontend SHALL display the final status prominently

### Requirement 10: Outreach and Contact Management

**User Story:** As a user, I want to collect and manage LinkedIn contacts for networking, so that I can expand my professional network during job hunting.

#### Acceptance Criteria

1. WHEN a user navigates to the Outreach section, THE Frontend SHALL display contact collection options
2. WHEN a user clicks "Collect Contacts", THE Frontend SHALL display configuration options for contact collection
3. WHEN a user clicks "Start Collecting", THE Frontend SHALL send a request to the Backend to begin contact collection
4. WHEN contacts are collected, THE Frontend SHALL display them in a list with relevant information
5. WHEN a user stops collecting contacts, THE Frontend SHALL send a stop request to the Backend

### Requirement 11: Overview Dashboard

**User Story:** As a user, I want to see an overview of my job hunting activities, so that I can quickly understand my progress and statistics.

#### Acceptance Criteria

1. WHEN a user navigates to the Overview section, THE Frontend SHALL display summary statistics
2. WHEN the Backend provides analytics data, THE Frontend SHALL visualize it with charts or cards
3. WHEN statistics update, THE Frontend SHALL refresh the overview display

### Requirement 12: Electron Desktop Application Integration

**User Story:** As a user, I want to use JobHuntr as a desktop application, so that I have a native application experience with system integration.

#### Acceptance Criteria

1. WHEN the application starts, THE Electron main process SHALL initialize and create the application window
2. WHEN the Frontend needs to access system resources, THE Electron main process SHALL provide secure IPC communication
3. WHEN the application updates are available, THE Electron updater SHALL notify the user
4. WHEN the user closes the application, THE Electron main process SHALL properly clean up resources

### Requirement 13: Supabase Integration and Data Persistence

**User Story:** As a system, I want to persist all user data to Supabase, so that data is securely stored and accessible across sessions.

#### Acceptance Criteria

1. WHEN the Frontend initializes, THE Frontend SHALL connect to Supabase using the project URL `https://jgnbsyihqwesjhewzohi.supabase.co`
2. WHEN user authentication occurs, THE Frontend SHALL use Supabase authentication with the anon API key
3. WHEN the Backend performs privileged operations, THE Backend SHALL use the service_role key
4. WHEN data is created or updated, THE System SHALL persist it to the appropriate Supabase tables
5. WHEN the Frontend queries data, THE System SHALL retrieve it from Supabase with proper authentication

### Requirement 14: Error Handling and User Feedback

**User Story:** As a user, I want clear error messages and feedback, so that I understand what went wrong and how to fix it.

#### Acceptance Criteria

1. WHEN an API request fails, THE Frontend SHALL display a user-friendly error message
2. WHEN a validation error occurs, THE Frontend SHALL highlight the problematic fields and explain the issue
3. WHEN a long-running operation is in progress, THE Frontend SHALL display a loading indicator
4. WHEN an operation completes successfully, THE Frontend SHALL display a success notification
5. WHEN the Backend is unreachable, THE Frontend SHALL display a connection error message

### Requirement 15: Responsive UI Layout and Navigation

**User Story:** As a user, I want a clean and intuitive interface, so that I can easily navigate and use all features.

#### Acceptance Criteria

1. WHEN the application loads, THE Frontend SHALL display a navigation sidebar with all main sections
2. WHEN a user clicks a navigation item, THE Frontend SHALL navigate to the corresponding section
3. WHEN a section is active, THE Frontend SHALL highlight it in the navigation
4. WHEN the UI renders, THE Frontend SHALL match the exact layout and styling shown in the reference screenshots
5. WHEN components are displayed, THE Frontend SHALL use TailwindCSS for consistent styling
