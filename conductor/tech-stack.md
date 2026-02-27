# ID8 Technology Stack

## Backend
- **Language:** Python 3.14
- **Framework:** FastAPI (async)
- **Database ORM:** SQLAlchemy 2.0 (async)
- **Database Driver:** asyncpg, psycopg
- **Migrations:** Alembic
- **Validation:** Pydantic v2
- **Configuration:** Pydantic Settings
- **HTTP Client:** httpx
- **AI Integration:** Google Gemini via `google-genai` SDK

## Frontend
- **Framework:** Next.js 15 (App Router)
- **Library:** React 19
- **Data Fetching:** TanStack Query 5
- **Styling:** Tailwind CSS 4
- **Language:** TypeScript 5
- **Icons/Components:** Custom built components with Tailwind utility classes.

## Database
- **Primary Database:** PostgreSQL 16
- **Hosting:** Supabase (for both database and potentially some backend logic)

## Deployment & Infrastructure
- **Frontend Hosting:** Vercel
- **Backend/DB Hosting:** Supabase
- **Secrets Management:** Environment variables (dotenv)
