# Design Document

## Overview

The JobHuntr frontend is an Electron-based desktop application built with React, Vite, and TailwindCSS. It provides a comprehensive user interface for automated job hunting across multiple platforms (LinkedIn, Indeed, Glassdoor, Dice, ZipRecruiter). The application integrates with a Python FastAPI backend, Supabase for authentication and data persistence, and multiple AI providers (Gemini, OpenAI, Anthropic) for resume optimization and cover letter generation.

The frontend architecture follows a component-based design with centralized state management using Zustand, real-time polling for activity updates, and a service gateway pattern for API communication.

## Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Electron Main Process                     │
│  - Window Management                                         │
│  - IPC Communication                                         │
│  - Auto-updater                                              │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│                  Electron Renderer Process                   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              React Application (Vite)                 │  │
│  │                                                        │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────┐ │  │
│  │  │   UI Layer   │  │  State Mgmt  │  │  Services  │ │  │
│  │  │  (Components)│  │   (Zustand)  │  │   Layer    │ │  │
│  │  └──────────────┘  └──────────────┘  └────────────┘ │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│                     Service Gateway                          │
│  - API Route Management                                      │
│  - Request/Response Transformation                           │
│  - Authentication Header Injection                           │
└─────┬──────────────┬──────────────┬────────────────────────┘
      │              │              │
┌─────▼─────┐  ┌────▼─────┐  ┌────▼──────┐
│  FastAPI  │  │ Supabase │  │ AI Models │
│  Backend  │  │   Auth   │  │  (Gemini, │
│           │  │   & DB   │  │  OpenAI)  │
└───────────┘  └──────────┘  └───────────┘
```

### Technology Stack

- **Desktop Framework**: Electron (v6.6.2 with electron-updater)
- **Frontend Framework**: React 19.1.1
- **Build Tool**: Vite
- **Styling**: TailwindCSS 4.1.10
- **State Management**: Zustand 5.0.5
- **HTTP Client**: Axios 1.10.0
- **Authentication**: Clerk React 5.32.1 (for Supabase integration)
- **Rich Text Editor**: TipTap 2.26.1
- **Animations**: Framer Motion 12.19.1
- **Icons**: Lucide React 0.523.0
- **Markdown**: React Markdown 10.1.0
- **Flow Diagrams**: ReactFlow 11.11.4

## Components and Interfaces

### Core Application Structure

```
src/
├── main/                    # Electron main process
│   ├── electron-main.ts     # Main entry point
│   ├── window-manager.ts    # Window lifecycle management
│   └── ipc-handlers.ts      # IPC communication handlers
│
├── renderer/                # React application
│   ├── App.tsx              # Root component with routing
│   ├── main.tsx             # Renderer entry point
│   │
│   ├── components/          # Reusable UI components
│   │   ├── layout/
│   │   │   ├── Sidebar.tsx
│   │   │   ├── Header.tsx
│   │   │   └── Layout.tsx
│   │   ├── common/
│   │   │   ├── Button.tsx
│   │   │   ├── Input.tsx
│   │   │   ├── Modal.tsx
│   │   │   ├── LoadingSpinner.tsx
│   │   │   └── Toast.tsx
│   │   └── features/
│   │       ├── ActivityLog.tsx
│   │       ├── JobCard.tsx
│   │       ├── ResumeEditor.tsx
│   │       └── ModelSelector.tsx
│   │
│   ├── pages/               # Page-level components
│   │   ├── Auth/
│   │   │   ├── Login.tsx
│   │   │   └── Signup.tsx
│   │   ├── Overview/
│   │   │   └── Overview.tsx
│   │   ├── AllRuns/
│   │   │   ├── AllRuns.tsx
│   │   │   ├── NewRun.tsx
│   │   │   └── RunDetails.tsx
│   │   ├── ATSResume/
│   │   │   ├── ATSResume.tsx
│   │   │   ├── CreateTemplate.tsx
│   │   │   └── TemplateResult.tsx
│   │   ├── CoverLetter/
│   │   │   ├── CoverLetter.tsx
│   │   │   └── CreateCoverLetter.tsx
│   │   ├── JobTracker/
│   │   │   ├── JobTracker.tsx
│   │   │   └── JobDetails.tsx
│   │   ├── InfiniteHunt/
│   │   │   └── InfiniteHunt.tsx
│   │   ├── Outreach/
│   │   │   └── Outreach.tsx
│   │   └── UserCenter/
│   │       ├── Profile.tsx
│   │       └── AboutMe.tsx
│   │
│   ├── services/            # API and business logic
│   │   ├── api/
│   │   │   ├── client.ts    # Axios instance with interceptors
│   │   │   ├── auth.ts      # Authentication API calls
│   │   │   ├── resume.ts    # Resume API calls
│   │   │   ├── coverLetter.ts
│   │   │   ├── workflow.ts
│   │   │   ├── infiniteHunt.ts
│   │   │   └── jobTracker.ts
│   │   ├── supabase.ts      # Supabase client configuration
│   │   └── polling.ts       # Activity polling service
│   │
│   ├── stores/              # Zustand state stores
│   │   ├── authStore.ts     # Authentication state
│   │   ├── workflowStore.ts # Workflow run state
│   │   ├── resumeStore.ts   # Resume management state
│   │   ├── infiniteHuntStore.ts
│   │   └── uiStore.ts       # UI state (modals, toasts)
│   │
│   ├── hooks/               # Custom React hooks
│   │   ├── useAuth.ts
│   │   ├── usePolling.ts
│   │   ├── useWorkflow.ts
│   │   └── useInfiniteHunt.ts
│   │
│   ├── types/               # TypeScript type definitions
│   │   ├── api.ts
│   │   ├── models.ts
│   │   └── store.ts
│   │
│   └── utils/               # Utility functions
│       ├── formatters.ts
│       ├── validators.ts
│       └── constants.ts
│
└── service-gateway/         # API gateway service
    ├── server.ts            # Express server
    ├── routes/
    │   ├── auth.ts
    │   ├── backend.ts       # Proxy to FastAPI backend
    │   ├── supabase.ts      # Supabase operations
    │   └── ai.ts            # AI provider routing
    ├── middleware/
    │   ├── auth.ts          # JWT verification
    │   └── errorHandler.ts
    └── config/
        └── env.ts           # Environment configuration
```

### Key Component Interfaces

#### Authentication Components

```typescript
// Login.tsx
interface LoginProps {
  onSuccess: (token: string) => void;
}

interface LoginFormData {
  email: string;
  password: string;
}

// Signup.tsx
interface SignupProps {
  onSuccess: (token: string) => void;
}

interface SignupFormData {
  email: string;
  password: string;
  confirmPassword: string;
}
```

#### Workflow Components

```typescript
// AllRuns.tsx
interface WorkflowRun {
  id: string;
  workflow_id: string;
  status: 'pending' | 'running' | 'paused' | 'stopped' | 'completed' | 'failed';
  created_at: string;
  updated_at: string;
  config: Record<string, any>;
}

interface AllRunsProps {
  runs: WorkflowRun[];
  onCreateNew: () => void;
  onSelectRun: (runId: string) => void;
}

// NewRun.tsx
interface NewRunProps {
  onSubmit: (config: WorkflowConfig) => Promise<void>;
  onCancel: () => void;
}

interface WorkflowConfig {
  platform: 'linkedin' | 'indeed' | 'glassdoor' | 'dice' | 'ziprecruiter';
  searchUrl?: string;
  filters: Record<string, any>;
  resumeId?: string;
  coverLetterTemplateId?: string;
}

// ActivityLog.tsx
interface ActivityLogProps {
  workflowRunId: string;
  autoScroll?: boolean;
}

interface ActivityEntry {
  timestamp: string;
  type: 'info' | 'success' | 'warning' | 'error';
  message: string;
  details?: Record<string, any>;
}
```

#### Resume Components

```typescript
// ATSResume.tsx
interface Resume {
  id: string;
  user_id: string;
  name: string;
  content: string;
  created_at: string;
  updated_at: string;
}

interface ATSResumeProps {
  resumes: Resume[];
  onCreateNew: () => void;
  onEdit: (resumeId: string) => void;
  onDelete: (resumeId: string) => void;
}

// CreateTemplate.tsx (Multi-step wizard)
interface CreateTemplateProps {
  onComplete: (resume: Resume) => void;
  onCancel: () => void;
}

interface TemplateWizardStep {
  step: 1 | 2 | 3 | 4 | 5;
  data: Partial<ResumeData>;
}

interface ResumeData {
  file?: File;
  content: string;
  experiences: Experience[];
  aiAnalysis?: AIAnalysisResult;
}

interface AIAnalysisResult {
  preview: string;
  analysis: {
    score: number;
    suggestions: string[];
    keywords: string[];
  };
  code: string;
  diff: string;
}
```

#### Infinite Hunt Components

```typescript
// InfiniteHunt.tsx
interface InfiniteHuntProps {
  status: InfiniteHuntStatus;
  onStart: () => Promise<void>;
  onPause: () => Promise<void>;
  onResume: () => Promise<void>;
  onStop: () => Promise<void>;
}

interface InfiniteHuntStatus {
  is_running: boolean;
  started_at: string | null;
  ended_at: string | null;
  active_agent_run_id: string | null;
  current_agent_run: {
    workflow_id: string;
    status: string;
    progress: number;
  } | null;
  cumulative_job_stats: {
    queued: number;
    skipped: number;
    submitted: number;
    failed: number;
  };
  agent_runs_by_template: Record<string, number>;
}
```

#### Model Selector Component

```typescript
// ModelSelector.tsx
interface ModelSelectorProps {
  value: ModelSelection;
  onChange: (selection: ModelSelection) => void;
}

interface ModelSelection {
  provider: AIProvider;
  model: string;
}

type AIProvider = 'gemini' | 'openai' | 'anthropic' | 'mistral';

interface ModelOption {
  provider: AIProvider;
  models: string[];
}

const MODEL_OPTIONS: ModelOption[] = [
  {
    provider: 'gemini',
    models: [
      'gemini-2.5-flash',
      'gemini-2.5-pro',
      'gemini-2.0-flash',
      'gemini-3.0-pro'
    ]
  },
  {
    provider: 'openai',
    models: ['gpt-4o', 'gpt-4.1', 'gpt-4.1-nano']
  },
  {
    provider: 'anthropic',
    models: ['claude-3-opus', 'claude-3-sonnet', 'claude-3-haiku']
  },
  {
    provider: 'mistral',
    models: ['mistral-large', 'mistral-medium', 'mistral-small']
  }
];
```

## Data Models

### Frontend Data Models

```typescript
// User and Authentication
interface User {
  id: string;
  email: string;
  created_at: string;
  metadata?: Record<string, any>;
}

interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
}

// Resume
interface Resume {
  id: string;
  user_id: string;
  name: string;
  content: string; // HTML or JSON
  created_at: string;
  updated_at: string;
}

// Cover Letter
interface CoverLetterTemplate {
  id: string;
  user_id: string;
  name: string;
  content: string;
  created_at: string;
  updated_at: string;
}

interface GeneratedCoverLetter {
  id: string;
  user_id: string;
  template_id: string;
  resume_id: string;
  job_title: string;
  company_name: string;
  content: string;
  created_at: string;
}

// Workflow
interface AgentRunTemplate {
  id: string;
  name: string; // e.g., "linkedin-apply", "indeed-search"
  display_name: string;
  platform: string;
  config_schema: Record<string, any>;
}

interface WorkflowRun {
  id: string;
  user_id: string;
  workflow_id: string;
  status: 'pending' | 'running' | 'paused' | 'stopped' | 'completed' | 'failed';
  config: Record<string, any>;
  created_at: string;
  updated_at: string;
  started_at?: string;
  completed_at?: string;
  error_message?: string;
  infinite_hunt_session_id?: string;
}

// Job Application
interface JobApplication {
  id: string;
  user_id: string;
  workflow_run_id?: string;
  company_name: string;
  job_title: string;
  job_url: string;
  platform: string;
  status: 'queued' | 'submitted' | 'skipped' | 'failed';
  applied_at?: string;
  created_at: string;
  updated_at: string;
  job_description?: string;
  notes?: string;
}

// Infinite Hunt
interface InfiniteRun {
  id: string;
  user_id: string;
  status: 'idle' | 'running' | 'paused' | 'stopped';
  session_id: string;
  last_run_id?: string;
  created_at: string;
  updated_at: string;
}

// User FAQ
interface UserFaq {
  id: string;
  user_id: string;
  question: string;
  answer: string;
  category?: string;
  created_at: string;
  updated_at: string;
}

// Activity Log Entry
interface ActivityLogEntry {
  id: string;
  workflow_run_id: string;
  timestamp: string;
  type: 'info' | 'success' | 'warning' | 'error';
  message: string;
  details?: Record<string, any>;
}
```

### API Request/Response Models

```typescript
// Authentication
interface LoginRequest {
  email: string;
  password: string;
}

interface LoginResponse {
  success: boolean;
  token: string;
  user: User;
}

// Workflow Control
interface StartWorkflowRequest {
  user_id: string;
  workflow_run_id: string;
  config: Record<string, any>;
}

interface StartWorkflowResponse {
  success: boolean;
  bot_id?: string;
  workflow_run_id: string;
  message: string;
}

interface WorkflowStatusResponse {
  success: boolean;
  is_running: boolean;
  status: string;
  current_url?: string;
  message?: string;
}

// Infinite Hunt
interface InfiniteHuntMetadataResponse {
  is_running: boolean;
  started_at: string | null;
  ended_at: string | null;
  agent_runs_by_template: Record<string, number>;
  current_agent_run: {
    workflow_id: string;
    status: string;
  } | null;
  cumulative_job_stats: {
    queued: number;
    skipped: number;
    submitted: number;
    failed: number;
  };
  auto_hunt_status?: {
    enabled: boolean;
    check_interval_minutes: number;
    last_auto_start_at: string | null;
  };
}

// Resume Generation
interface GenerateResumeRequest {
  resume_id: string;
  job_description: string;
  model: string;
}

interface GenerateResumeResponse {
  success: boolean;
  preview: string;
  analysis: {
    score: number;
    suggestions: string[];
    keywords: string[];
  };
  code: string;
  diff: string;
}

// Cover Letter Generation
interface GenerateCoverLetterRequest {
  template_id: string;
  resume_id: string;
  job_title: string;
  company_name: string;
  job_description: string;
  model: string;
}

interface GenerateCoverLetterResponse {
  success: boolean;
  content: string;
  cover_letter_id: string;
}
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*


### Property Reflection

After analyzing all acceptance criteria, I've identified several areas where properties can be consolidated:

**Redundancy Analysis:**
- Properties 3.3 and 3.5 (template/resume loading) can be combined into a single "data loading" property
- Properties 6.7 and 9.2 (displaying updates) are similar and can be unified
- Properties 13.4 and 13.5 (Supabase operations) can be combined into a round-trip property
- Properties 14.1, 14.2, 14.3, 14.4 (user feedback) can be consolidated into a comprehensive feedback property

**Consolidated Properties:**
After reflection, we'll focus on unique, high-value properties that provide distinct validation:
- Authentication and token management (1.2, 1.3)
- Data persistence round-trips (1.5, 2.8, 13.4)
- API request integrity (2.3, 2.6, 3.6, 5.5, 7.5, 8.1, 8.2, 8.3)
- Real-time updates and polling (4.3, 5.7, 9.1, 9.2)
- Model selection and configuration (7.2, 7.4)
- Error handling and user feedback (14.1-14.4 combined)

### Correctness Properties

**Property 1: Authentication token persistence**
*For any* valid user credentials, when authentication succeeds, the JWT token should be stored and retrievable for subsequent requests
**Validates: Requirements 1.2, 1.3**

**Property 2: Data persistence round-trip**
*For any* user data (About Me, resume, cover letter), when saved to Supabase, retrieving it should return equivalent data
**Validates: Requirements 1.5, 2.8, 13.4**

**Property 3: File upload transmission**
*For any* valid resume file, when uploaded, the file should be transmitted to the backend with correct content and metadata
**Validates: Requirements 2.3**

**Property 4: AI analysis result completeness**
*For any* AI analysis response, the result should contain all three required sections: preview, analysis, and code
**Validates: Requirements 2.7**

**Property 5: Template data loading**
*For any* template or resume selection, the corresponding data should be loaded and available for use in the current context
**Validates: Requirements 3.3, 3.5**

**Property 6: AI request payload completeness**
*For any* AI operation request (resume optimization, cover letter generation), the request should include all required fields: content, job information, and selected model identifier
**Validates: Requirements 3.6, 7.5**

**Property 7: Job detail display completeness**
*For any* job entry, when clicked, the detail view should display all required fields: company, position, status, and application date
**Validates: Requirements 4.2**

**Property 8: Real-time state synchronization**
*For any* backend state update (application status, job statistics), the frontend should reflect the change within the polling interval
**Validates: Requirements 4.3, 6.7**

**Property 9: Configuration validation and storage**
*For any* workflow configuration, when validated and stored, retrieving it should return the same configuration
**Validates: Requirements 5.4**

**Property 10: Activity log append-only behavior**
*For any* new activity log entries, they should be appended to the existing log without removing or modifying previous entries
**Validates: Requirements 5.7, 9.2**

**Property 11: Model provider mapping**
*For any* AI provider selection, the model dropdown should be populated with exactly the models defined for that provider
**Validates: Requirements 7.2**

**Property 12: Active model persistence**
*For any* model selection, the selection should be stored and used consistently across all subsequent AI operations until changed
**Validates: Requirements 7.4**

**Property 13: API routing correctness**
*For any* API request, the service gateway should route it to the correct backend endpoint based on the request path and method
**Validates: Requirements 8.1**

**Property 14: Authentication header injection**
*For any* authenticated API request, the service gateway should include the JWT token in the Authorization header
**Validates: Requirements 8.2, 13.5**

**Property 15: Polling interval consistency**
*For any* active workflow run, activity updates should be polled at regular intervals (not more frequently than configured)
**Validates: Requirements 9.1**

**Property 16: Status formatting consistency**
*For any* activity log entry with status information, it should be displayed with both appropriate formatting (color/style) and an icon
**Validates: Requirements 9.3**

**Property 17: IPC security boundary**
*For any* system resource access request from the renderer, the main process should validate the request before granting access
**Validates: Requirements 12.2**

**Property 18: Resource cleanup on exit**
*For any* application close event, all open connections, timers, and file handles should be properly closed
**Validates: Requirements 12.4**

**Property 19: Supabase authentication key usage**
*For any* authentication operation, the frontend should use the anon key, and for any privileged operation, the backend should use the service_role key
**Validates: Requirements 13.2, 13.3**

**Property 20: Error feedback completeness**
*For any* error condition (API failure, validation error, connection error), the frontend should display a user-friendly message explaining the issue
**Validates: Requirements 14.1, 14.2, 14.5**

**Property 21: Loading state indication**
*For any* asynchronous operation, a loading indicator should be displayed from operation start until completion or error
**Validates: Requirements 14.3**

**Property 22: Success notification**
*For any* successful operation (save, submit, update), a success notification should be displayed to the user
**Validates: Requirements 14.4**

**Property 23: Navigation routing**
*For any* navigation item click, the application should navigate to the correct route and update the active state in the sidebar
**Validates: Requirements 15.2, 15.3**

## Error Handling

### Error Categories

1. **Network Errors**
   - Connection timeout
   - Backend unreachable
   - Service gateway unavailable
   - Supabase connection failure

2. **Authentication Errors**
   - Invalid credentials
   - Expired token
   - Insufficient permissions
   - Session timeout

3. **Validation Errors**
   - Invalid form input
   - Missing required fields
   - File type/size restrictions
   - Configuration schema violations

4. **Business Logic Errors**
   - Workflow already running
   - Resource not found
   - Duplicate entries
   - State conflicts

5. **System Errors**
   - File system access denied
   - Memory allocation failure
   - IPC communication failure
   - Electron process crash

### Error Handling Strategy

```typescript
// Centralized error handler
class ErrorHandler {
  handle(error: AppError): void {
    // Log error for debugging
    console.error('[ErrorHandler]', error);
    
    // Determine error category
    const category = this.categorizeError(error);
    
    // Display user-friendly message
    const message = this.getUserMessage(error, category);
    this.showToast(message, 'error');
    
    // Handle specific error types
    switch (category) {
      case 'auth':
        this.handleAuthError(error);
        break;
      case 'network':
        this.handleNetworkError(error);
        break;
      case 'validation':
        this.handleValidationError(error);
        break;
      default:
        this.handleGenericError(error);
    }
  }
  
  private handleAuthError(error: AppError): void {
    // Clear invalid token
    authStore.clearAuth();
    // Redirect to login
    router.push('/login');
  }
  
  private handleNetworkError(error: AppError): void {
    // Retry logic for transient failures
    if (error.retryable) {
      this.scheduleRetry(error.operation);
    }
  }
  
  private handleValidationError(error: AppError): void {
    // Highlight problematic fields
    if (error.fields) {
      error.fields.forEach(field => {
        this.highlightField(field, error.message);
      });
    }
  }
}
```

### Error Recovery Mechanisms

1. **Automatic Retry**
   - Network requests: 3 retries with exponential backoff
   - Polling failures: Continue polling with increased interval
   - File uploads: Resume from last successful chunk

2. **Graceful Degradation**
   - Offline mode: Cache operations and sync when online
   - Partial failures: Display available data with error indicators
   - Fallback UI: Show simplified interface if components fail

3. **User-Initiated Recovery**
   - Refresh button for stale data
   - Retry button for failed operations
   - Clear cache option for corrupted state

## Testing Strategy

### Unit Testing

**Framework**: Vitest with React Testing Library

**Coverage Areas**:
- Component rendering and props
- User interactions (clicks, form submissions)
- State management (Zustand stores)
- Utility functions (formatters, validators)
- API client methods

**Example Unit Tests**:
```typescript
// Button component
describe('Button', () => {
  it('renders with correct text', () => {
    render(<Button>Click me</Button>);
    expect(screen.getByText('Click me')).toBeInTheDocument();
  });
  
  it('calls onClick handler when clicked', () => {
    const handleClick = vi.fn();
    render(<Button onClick={handleClick}>Click</Button>);
    fireEvent.click(screen.getByText('Click'));
    expect(handleClick).toHaveBeenCalledOnce();
  });
  
  it('is disabled when loading', () => {
    render(<Button loading>Click</Button>);
    expect(screen.getByRole('button')).toBeDisabled();
  });
});

// Auth store
describe('authStore', () => {
  it('sets user and token on login', () => {
    const user = { id: '1', email: 'test@example.com' };
    const token = 'jwt-token';
    
    authStore.login(user, token);
    
    expect(authStore.user).toEqual(user);
    expect(authStore.token).toBe(token);
    expect(authStore.isAuthenticated).toBe(true);
  });
  
  it('clears state on logout', () => {
    authStore.login({ id: '1', email: 'test@example.com' }, 'token');
    authStore.logout();
    
    expect(authStore.user).toBeNull();
    expect(authStore.token).toBeNull();
    expect(authStore.isAuthenticated).toBe(false);
  });
});
```

### Property-Based Testing

**Framework**: fast-check (JavaScript property-based testing library)

**Configuration**: Each property test should run a minimum of 100 iterations

**Test Tagging**: Each property-based test must include a comment with the format:
`// **Feature: frontend-restoration, Property {number}: {property_text}**`

**Property Test Examples**:

```typescript
import fc from 'fast-check';

// **Feature: frontend-restoration, Property 1: Authentication token persistence**
describe('Property 1: Authentication token persistence', () => {
  it('should store and retrieve JWT token for any valid credentials', () => {
    fc.assert(
      fc.property(
        fc.emailAddress(),
        fc.string({ minLength: 8 }),
        async (email, password) => {
          // Arrange: Generate valid credentials
          const credentials = { email, password };
          
          // Act: Authenticate
          const response = await authService.login(credentials);
          
          // Assert: Token should be stored and retrievable
          expect(response.token).toBeDefined();
          expect(authStore.token).toBe(response.token);
          expect(localStorage.getItem('auth_token')).toBe(response.token);
        }
      ),
      { numRuns: 100 }
    );
  });
});

// **Feature: frontend-restoration, Property 2: Data persistence round-trip**
describe('Property 2: Data persistence round-trip', () => {
  it('should retrieve equivalent data after saving to Supabase', () => {
    fc.assert(
      fc.property(
        fc.record({
          name: fc.string({ minLength: 1, maxLength: 100 }),
          content: fc.string({ minLength: 10, maxLength: 5000 }),
        }),
        async (resumeData) => {
          // Arrange: Generate random resume data
          const userId = 'test-user-id';
          
          // Act: Save to Supabase
          const saved = await resumeService.create(userId, resumeData);
          
          // Retrieve from Supabase
          const retrieved = await resumeService.getById(saved.id);
          
          // Assert: Retrieved data should match saved data
          expect(retrieved.name).toBe(resumeData.name);
          expect(retrieved.content).toBe(resumeData.content);
        }
      ),
      { numRuns: 100 }
    );
  });
});

// **Feature: frontend-restoration, Property 11: Model provider mapping**
describe('Property 11: Model provider mapping', () => {
  it('should populate models dropdown with correct models for any provider', () => {
    fc.assert(
      fc.property(
        fc.constantFrom('gemini', 'openai', 'anthropic', 'mistral'),
        (provider) => {
          // Arrange: Get expected models for provider
          const expectedModels = MODEL_OPTIONS.find(
            opt => opt.provider === provider
          )?.models || [];
          
          // Act: Select provider
          const component = render(<ModelSelector />);
          fireEvent.change(component.getByLabelText('Provider'), {
            target: { value: provider }
          });
          
          // Assert: Models dropdown should contain exactly the expected models
          const modelOptions = component.getAllByRole('option', { 
            name: /gemini|gpt|claude|mistral/ 
          });
          const actualModels = modelOptions.map(opt => opt.value);
          
          expect(actualModels.sort()).toEqual(expectedModels.sort());
        }
      ),
      { numRuns: 100 }
    );
  });
});

// **Feature: frontend-restoration, Property 10: Activity log append-only behavior**
describe('Property 10: Activity log append-only behavior', () => {
  it('should append new entries without modifying existing ones', () => {
    fc.assert(
      fc.property(
        fc.array(fc.record({
          timestamp: fc.date(),
          type: fc.constantFrom('info', 'success', 'warning', 'error'),
          message: fc.string({ minLength: 1, maxLength: 200 }),
        }), { minLength: 1, maxLength: 20 }),
        fc.array(fc.record({
          timestamp: fc.date(),
          type: fc.constantFrom('info', 'success', 'warning', 'error'),
          message: fc.string({ minLength: 1, maxLength: 200 }),
        }), { minLength: 1, maxLength: 10 }),
        (initialEntries, newEntries) => {
          // Arrange: Initialize activity log with initial entries
          const store = createActivityLogStore();
          initialEntries.forEach(entry => store.addEntry(entry));
          const initialCount = store.entries.length;
          const initialEntriesCopy = [...store.entries];
          
          // Act: Add new entries
          newEntries.forEach(entry => store.addEntry(entry));
          
          // Assert: All initial entries should still exist unchanged
          expect(store.entries.length).toBe(initialCount + newEntries.length);
          initialEntriesCopy.forEach((entry, index) => {
            expect(store.entries[index]).toEqual(entry);
          });
        }
      ),
      { numRuns: 100 }
    );
  });
});

// **Feature: frontend-restoration, Property 14: Authentication header injection**
describe('Property 14: Authentication header injection', () => {
  it('should include JWT token in Authorization header for any authenticated request', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 20 }), // JWT token
        fc.constantFrom('GET', 'POST', 'PUT', 'DELETE'), // HTTP method
        fc.webPath(), // API endpoint
        async (token, method, endpoint) => {
          // Arrange: Set auth token
          authStore.setToken(token);
          
          // Act: Make API request
          const requestSpy = vi.spyOn(axios, 'request');
          await apiClient.request({ method, url: endpoint });
          
          // Assert: Request should include Authorization header
          expect(requestSpy).toHaveBeenCalledWith(
            expect.objectContaining({
              headers: expect.objectContaining({
                Authorization: `Bearer ${token}`
              })
            })
          );
        }
      ),
      { numRuns: 100 }
    );
  });
});
```

### Integration Testing

**Framework**: Playwright for end-to-end testing

**Coverage Areas**:
- Complete user workflows (signup → create resume → apply to job)
- Multi-step wizards (resume creation, cover letter generation)
- Real-time updates (activity logs, infinite hunt status)
- Cross-component interactions
- Electron-specific features (IPC, window management)

**Example Integration Tests**:
```typescript
test('complete resume creation workflow', async ({ page }) => {
  // Login
  await page.goto('/login');
  await page.fill('[name="email"]', 'test@example.com');
  await page.fill('[name="password"]', 'password123');
  await page.click('button[type="submit"]');
  
  // Navigate to ATS Resume
  await page.click('text=ATS Resume');
  await page.click('text=Create New Template');
  
  // Step 1: Upload file
  await page.setInputFiles('input[type="file"]', 'test-resume.pdf');
  await page.click('text=Next');
  
  // Step 2: Edit content
  await page.fill('[contenteditable]', 'Updated resume content');
  await page.click('text=Next');
  
  // Step 3: Add experience
  await page.click('text=Add Experience');
  await page.fill('[name="company"]', 'Test Company');
  await page.fill('[name="position"]', 'Software Engineer');
  await page.click('text=Next');
  
  // Step 4: Test with AI
  await page.click('text=Test');
  await page.waitForSelector('text=Analysis Complete');
  await page.click('text=Next');
  
  // Step 5: Review and save
  await expect(page.locator('.preview-section')).toBeVisible();
  await expect(page.locator('.analysis-section')).toBeVisible();
  await expect(page.locator('.code-section')).toBeVisible();
  await page.click('text=Save Template');
  
  // Verify template appears in list
  await expect(page.locator('text=Updated resume content')).toBeVisible();
});

test('infinite hunt start and monitor', async ({ page }) => {
  await page.goto('/infinite-hunt');
  
  // Start infinite hunt
  await page.click('text=Start Infinite Hunt');
  
  // Verify status updates
  await expect(page.locator('text=Running')).toBeVisible();
  await expect(page.locator('[data-testid="job-stats"]')).toBeVisible();
  
  // Wait for activity updates
  await page.waitForTimeout(5000);
  const activityCount = await page.locator('.activity-entry').count();
  expect(activityCount).toBeGreaterThan(0);
  
  // Pause
  await page.click('text=Pause');
  await expect(page.locator('text=Paused')).toBeVisible();
  
  // Resume
  await page.click('text=Resume');
  await expect(page.locator('text=Running')).toBeVisible();
  
  // Stop
  await page.click('text=Stop');
  await expect(page.locator('text=Idle')).toBeVisible();
});
```

### Manual Testing Checklist

- [ ] Visual comparison with reference screenshots for all pages
- [ ] Responsive layout on different window sizes
- [ ] Keyboard navigation and accessibility
- [ ] Error scenarios (network failures, invalid inputs)
- [ ] Performance with large datasets (many jobs, long activity logs)
- [ ] Electron-specific features (window controls, system tray, notifications)
- [ ] Cross-platform compatibility (Windows, macOS, Linux)

## Service Gateway Implementation

### Architecture

The service gateway acts as a middleware layer between the frontend and backend services. It handles:
- Request routing
- Authentication header injection
- Response transformation
- Error handling
- Environment-based configuration

### Technology Stack

- **Framework**: Express.js
- **Language**: TypeScript
- **HTTP Client**: Axios (for proxying to backend)
- **Authentication**: JWT verification

### Directory Structure

```
service-gateway/
├── src/
│   ├── server.ts              # Main server entry point
│   ├── config/
│   │   └── env.ts             # Environment configuration
│   ├── middleware/
│   │   ├── auth.ts            # JWT verification middleware
│   │   ├── errorHandler.ts   # Global error handler
│   │   └── logger.ts          # Request logging
│   ├── routes/
│   │   ├── index.ts           # Route aggregation
│   │   ├── auth.ts            # Authentication routes
│   │   ├── backend.ts         # Backend proxy routes
│   │   ├── supabase.ts        # Supabase operations
│   │   └── ai.ts              # AI provider routing
│   ├── services/
│   │   ├── supabaseClient.ts  # Supabase client wrapper
│   │   └── aiProviders.ts     # AI provider clients
│   └── types/
│       └── index.ts           # TypeScript types
├── package.json
├── tsconfig.json
└── .env.example
```

### Key Implementation Details

```typescript
// server.ts
import express from 'express';
import cors from 'cors';
import { authMiddleware } from './middleware/auth';
import { errorHandler } from './middleware/errorHandler';
import routes from './routes';

const app = express();

app.use(cors());
app.use(express.json());
app.use('/api', routes);
app.use(errorHandler);

const PORT = process.env.PORT || 3001;
app.listen(PORT, () => {
  console.log(`Service gateway running on port ${PORT}`);
});

// routes/backend.ts - Proxy to FastAPI backend
import { Router } from 'express';
import axios from 'axios';
import { authMiddleware } from '../middleware/auth';

const router = Router();
const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';

router.use(authMiddleware);

router.all('/*', async (req, res, next) => {
  try {
    const response = await axios({
      method: req.method,
      url: `${BACKEND_URL}${req.path}`,
      data: req.body,
      params: req.query,
      headers: {
        ...req.headers,
        host: undefined, // Remove host header
      },
    });
    
    res.status(response.status).json(response.data);
  } catch (error) {
    next(error);
  }
});

export default router;

// routes/ai.ts - AI provider routing
import { Router } from 'express';
import { authMiddleware } from '../middleware/auth';
import { getAIProvider } from '../services/aiProviders';

const router = Router();

router.use(authMiddleware);

router.post('/generate', async (req, res, next) => {
  try {
    const { provider, model, prompt } = req.body;
    
    const aiClient = getAIProvider(provider);
    const result = await aiClient.generate(model, prompt);
    
    res.json({ success: true, result });
  } catch (error) {
    next(error);
  }
});

export default router;
```

### Environment Configuration

```bash
# .env.example
NODE_ENV=development
PORT=3001

# Backend
BACKEND_URL=http://localhost:8000

# Supabase
SUPABASE_URL=https://jgnbsyihqwesjhewzohi.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key

# AI Providers
GEMINI_API_KEY=your-gemini-key
OPENAI_API_KEY=your-openai-key
ANTHROPIC_API_KEY=your-anthropic-key
MISTRAL_API_KEY=your-mistral-key

# Railway (production)
RAILWAY_BACKEND_URL=https://your-backend.railway.app
```

## Deployment Strategy

### Development Environment

1. **Backend**: Run locally on `http://localhost:8000`
2. **Service Gateway**: Run locally on `http://localhost:3001`
3. **Frontend**: Run in Electron dev mode with Vite HMR

### Production Environment (Railway)

1. **Backend**: Deploy to Railway as a Python service
2. **Service Gateway**: Deploy to Railway as a Node.js service
3. **Frontend**: Package as Electron app with production service gateway URL

### Build Process

```bash
# Backend
cd backend
pip install -r requirements.txt
python fastapi_server.py

# Service Gateway
cd service-gateway
npm install
npm run build
npm start

# Frontend
cd frontend
npm install
npm run build
npm run package  # Creates Electron distributable
```

## Security Considerations

1. **Authentication**
   - JWT tokens stored securely in localStorage
   - Tokens included in all authenticated requests
   - Token expiration handled gracefully

2. **API Keys**
   - Never exposed in frontend code
   - Managed by service gateway
   - Stored in environment variables

3. **IPC Security**
   - Validate all IPC messages
   - Sanitize file paths
   - Restrict system access

4. **Data Validation**
   - Validate all user inputs
   - Sanitize data before sending to backend
   - Prevent XSS and injection attacks

## Performance Optimization

1. **Code Splitting**
   - Lazy load routes
   - Dynamic imports for heavy components
   - Separate vendor bundles

2. **Caching**
   - Cache API responses
   - Memoize expensive computations
   - Use React.memo for pure components

3. **Polling Optimization**
   - Adaptive polling intervals
   - Stop polling when window is inactive
   - Batch multiple requests

4. **Asset Optimization**
   - Compress images
   - Minify CSS and JavaScript
   - Use CDN for static assets

## Accessibility

1. **Keyboard Navigation**
   - All interactive elements accessible via keyboard
   - Logical tab order
   - Visible focus indicators

2. **Screen Readers**
   - Semantic HTML elements
   - ARIA labels where needed
   - Alt text for images

3. **Color Contrast**
   - WCAG AA compliance
   - High contrast mode support
   - Color-blind friendly palette

4. **Responsive Design**
   - Scalable text
   - Flexible layouts
   - Touch-friendly targets
