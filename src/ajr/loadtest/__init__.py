"""Load test of the Data API: every api function with the kinds of arguments the
site sends, through PostgREST, as the site calls them.

    python -m ajr.loadtest --api http://localhost:3000 --plan --writes --out head.json
    python -m ajr.loadtest --api https://<ref>.supabase.co/rest/v1 --key <publishable key>
    python -m ajr.loadtest.report base.json head.json   # markdown: main -> PR

The cases are picked from the API's own answers (a weight's leader, an old
tournament, a nation with one athlete…), so the same run works on a copy of the
database and on production (read only: count_matchup writes and runs with
--writes only). A run fails on any answer but a success (2xx): a timeout (statement timeout:
HTTP 500), a server error, arguments the API refuses. How many pages each call
reads (--plan: PostgREST's EXPLAIN, a local copy only) and the times are
reported, not judged: they depend on the machine.
"""
