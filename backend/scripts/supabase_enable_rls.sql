-- Run once in the Supabase SQL editor after `alembic upgrade head`.
--
-- Supabase exposes an auto-generated REST API over the public schema. CareBridge does not
-- use it: only the backend talks to the database. Enabling row level security with no
-- policies makes that REST API return nothing for these tables. The backend connects as
-- the table owner (the role in DATABASE_URL), which is not subject to RLS.
DO $$
DECLARE t record;
BEGIN
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t.tablename);
  END LOOP;
END $$;
