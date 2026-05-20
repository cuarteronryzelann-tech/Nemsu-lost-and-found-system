# Neon (PostgreSQL) Setup Guide

This app uses **Neon** as its cloud database — a free, serverless PostgreSQL service.

## 1. Create a Neon project

1. Go to [https://neon.tech](https://neon.tech) and sign up (free).
2. Click **New Project**, give it a name (e.g. `nemsu-laf`), choose a region close to your deployment.
3. Neon will create a default database called `neondb`.

## 2. Get your connection string

In the Neon dashboard, open your project and click **Connection Details**.
Copy the **Connection string** — it looks like:

```
postgresql://user:password@ep-cool-name-123456.us-east-2.aws.neon.tech/neondb?sslmode=require
```

## 3. Set the environment variable

### On Render (production)

In your Render service → **Environment** tab, add:

| Key            | Value                                         |
|----------------|-----------------------------------------------|
| `DATABASE_URL` | `postgresql://user:password@ep-xxx.aws.neon.tech/neondb?sslmode=require` |

### Local development

Create a `.env` file (never commit this!) or export the variable:

```bash
export DATABASE_URL="postgresql://user:password@ep-xxx.aws.neon.tech/neondb?sslmode=require"
```

Or install `python-dotenv` and add it to a `.env` file.

## 4. Tables are created automatically

`init_db()` runs on startup and creates all tables using `CREATE TABLE IF NOT EXISTS`,
so you don't need to run any migrations manually.

## 5. Local fallback (no DATABASE_URL)

If `DATABASE_URL` is not set, the app automatically falls back to a local SQLite file
at the path configured by `DATABASE_PATH` (default: `/tmp/nemsu_laf.db`).
This is useful for offline development without touching your cloud database.

## Free tier limits

| Resource         | Neon Free Tier |
|------------------|----------------|
| Storage          | 512 MB         |
| Compute          | 191.9 compute hours/month |
| Databases        | 1 project, 10 branches |
| Connection limit | Unlimited (serverless) |

For a student project this is more than enough.

## Troubleshooting

**`psycopg2.OperationalError: SSL connection required`**
→ Make sure `?sslmode=require` is at the end of your connection string.

**Tables not found after deploy**
→ The app calls `init_db()` on startup. Check that `DATABASE_URL` is set correctly in Render.

**`psycopg2` not installed**
→ Run `pip install -r requirements.txt`. The package is `psycopg2-binary`.
