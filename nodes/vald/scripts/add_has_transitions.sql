-- one-off upgrade of DBs imported before Species.has_transitions existed
-- usage: sqlite3 vald_all.sqlite < scripts/add_has_transitions.sql
ALTER TABLE species ADD COLUMN has_transitions bool NOT NULL DEFAULT 0;
CREATE INDEX species_has_transitions_71489c2f ON species (has_transitions);
UPDATE species SET has_transitions = EXISTS (SELECT 1 FROM transitions WHERE transitions.species_id = species.id);
UPDATE species SET inchi = 'InChI=1S/H2O/h1H2', inchikey = 'XLYOFNOQVPJJNP-UHFFFAOYSA-N' WHERE id = 10020;
ANALYZE species;
SELECT count(*) AS species_total, sum(has_transitions) AS with_lines FROM species;
