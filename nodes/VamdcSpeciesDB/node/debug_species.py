"""Replay the import of a single species from a node, step by step, and report
which step fails. Database changes are rolled back at the end.

usage (from the VamdcSpeciesDB directory):
    DJANGO_SETTINGS_MODULE=settings python3 node/debug_species.py <inchikey> [<node ivo identifier>]

example:
    DJANGO_SETTINGS_MODULE=settings python3 node/debug_species.py APKBIZXUJLWQRU-UHFFFAOYSA-N ivo://vamdc/vald/uu/all
"""
import sys
import traceback
import util

util.append_base_path(2)

import django
import settings
django.setup()

from django.db import transaction
from node.models import VamdcNodes, VamdcNodeSpecies
import node.import_functions as update
import vamdclib.nodes as vl_registry


class Rollback(Exception):
    pass


def show(label, value):
    print("  %-28s %r" % (label, value))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    inchikey = sys.argv[1]
    ivo = sys.argv[2] if len(sys.argv) > 2 else "ivo://vamdc/vald/uu/all"

    print("querying %s ..." % ivo)
    vl_node = vl_registry.Nodelist().getnode(ivo)
    vl_atoms, vl_molecules = update.get_species(vl_node)
    db_node = VamdcNodes.objects.get(ivo_identifier=ivo)

    found = [("molecule", m) for m in vl_molecules.values()
             if getattr(m, "InChIKey", None) == inchikey]
    found += [("atom", a) for a in vl_atoms.values()
              if getattr(a, "InChIKey", None) == inchikey]

    if not found:
        print("%s is not returned by %s (%d atoms, %d molecules received)"
              % (inchikey, ivo, len(vl_atoms), len(vl_molecules)))
        return

    for kind, vl_species in found:
        print("\n=== %s %s" % (kind, inchikey))
        for attr in ("VAMDCSpeciesID", "InChI", "InChIKey", "StoichiometricFormula",
                     "OrdinaryStructuralFormula", "ChemicalName", "MolecularWeight",
                     "MassNumber", "IonCharge"):
            show(attr, getattr(vl_species, attr, "<absent>"))
        try:
            with transaction.atomic():
                # same functions as the cron import
                if kind == "molecule":
                    update.load_molecule(db_node, vl_species)
                else:
                    update.load_atom(db_node, vl_species)
                print("  node_species rows for this species after import:")
                for ns in VamdcNodeSpecies.objects.filter(species_id=vl_species.VAMDCSpeciesID,
                                                          member_database=db_node):
                    show("  id=%s" % ns.id, "mass=%s formula=%s deprecated=%s"
                         % (ns.member_database_mass_number,
                            ns.database_species_formula_id, ns.deprecated))
                raise Rollback()
        except Rollback:
            print("  => all steps succeeded (changes rolled back)")
        except Exception:
            print("  => FAILED:")
            traceback.print_exc(file=sys.stdout)


if __name__ == "__main__":
    main()
