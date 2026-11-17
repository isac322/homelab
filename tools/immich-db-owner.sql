-- Apply once as postgres to cnpg-immich's app database before switching Immich
-- to cnpg-immich-app. Re-running is safe. Extension objects remain operator-owned;
-- the Database resource reconciles extensions without granting app superuser.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL lock_timeout = '10s';
DO $migration$
DECLARE
  object record;
BEGIN
  IF current_database() <> 'app' THEN
    RAISE EXCEPTION 'This migration is restricted to database app';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app' AND NOT rolsuper
                 AND NOT rolcreatedb AND NOT rolcreaterole AND rolcanlogin) THEN
    RAISE EXCEPTION 'Expected existing low-privilege CNPG app role';
  END IF;
  FOR object IN
    SELECT c.oid, c.relkind, n.nspname, c.relname
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relowner = 'postgres'::regrole
      AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
      AND NOT EXISTS (SELECT FROM pg_depend d WHERE d.classid = 'pg_class'::regclass
                      AND d.objid = c.oid AND d.deptype = 'e')
    ORDER BY CASE WHEN c.relkind = 'S' THEN 1 ELSE 0 END, c.oid
  LOOP
    EXECUTE format('ALTER %s %I.%I OWNER TO app',
      CASE object.relkind WHEN 'v' THEN 'VIEW' WHEN 'm' THEN 'MATERIALIZED VIEW'
        WHEN 'S' THEN 'SEQUENCE' WHEN 'f' THEN 'FOREIGN TABLE' ELSE 'TABLE' END,
      object.nspname, object.relname);
  END LOOP;
  FOR object IN
    SELECT p.oid::regprocedure AS signature
    FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public' AND p.proowner = 'postgres'::regrole
      AND NOT EXISTS (SELECT FROM pg_depend d WHERE d.classid = 'pg_proc'::regclass
                      AND d.objid = p.oid AND d.deptype = 'e')
  LOOP
    EXECUTE format('ALTER ROUTINE %s OWNER TO app', object.signature);
  END LOOP;
  FOR object IN
    SELECT t.oid::regtype AS name
    FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE n.nspname = 'public' AND t.typowner = 'postgres'::regrole
      AND t.typtype IN ('e', 'd')
      AND NOT EXISTS (SELECT FROM pg_depend d WHERE d.classid = 'pg_type'::regclass
                      AND d.objid = t.oid AND d.deptype = 'e')
  LOOP
    EXECUTE format('ALTER TYPE %s OWNER TO app', object.name);
  END LOOP;
END
$migration$;
COMMIT;
