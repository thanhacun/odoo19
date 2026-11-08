#!/bin/sh
# Compare what two import runs wrote: md5 per row of every column that is not an id/date-of-write, keyed by the legacy external id.
#   tools/compare_import_tables.sh <dbA> <dbB> <odoo table> <model> [where on t (alias t)]
# Many2one id columns (…_id) are left out (ids differ between databases); the many2many side tables are not compared here.
set -eu
A=$1; B=$2; TABLE=$3; MODEL=$4; WHERE=${5:-true}
PG="docker exec db psql -U odoo"
COLS=$($PG -d "$A" -Atc "select string_agg(quote_literal(column_name), ',') from information_schema.columns where table_name='$TABLE' and (column_name in ('create_date','write_date','create_uid','write_uid','id') or column_name like '%\\_id' or column_name like '%\\_ids')")
Q="select d.name, md5((to_jsonb(t) - ARRAY[$COLS])::text) from $TABLE t join ir_model_data d on d.model='$MODEL' and d.res_id=t.id and d.module='legacy12' where $WHERE order by 1"
$PG -d "$A" -Atc "$Q" > /tmp/cmpA.$$; $PG -d "$B" -Atc "$Q" > /tmp/cmpB.$$
echo "$TABLE: A=$(wc -l < /tmp/cmpA.$$) rows, B=$(wc -l < /tmp/cmpB.$$) rows, different: $(diff /tmp/cmpA.$$ /tmp/cmpB.$$ | grep -c '^<')"
rm -f /tmp/cmpA.$$ /tmp/cmpB.$$
