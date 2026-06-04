# -*- coding: utf-8 -*-
"""
ExampleNode dictionary definitions.
"""

# The returnable dictionary is used internally by the node and defines
# all the ways the VAMDC standard keywords (left-hand side) maps to
# the internal database representation queryset (right-hand side)
#
# When writing this, it helps to remember that dictionary is applied
# in a loop to every matching *instance* of the queryset variables
# returned from queryfunc.py. So in the example below, all 'AtomStates'
# will be looped over by the node software, using the name 'AtomState'
# (singular). 'AtomState' will be one single instance of a matching
# database object, from which we extract everything we need by parsing
# the VAMDC_standard LHS of this dictionary to how it maps to our specific
# database on the RHS. So, when looping through all AtomState objects
# matching the given query, the generator will for example know that
# to get the AtomStateEnergy VAMDC value, it will need to look at
# the AtomState.energy, i.e. the "energy" property of the current
# database object being worked on.
#
# (if you look at queryfuncs.py, you'll see 'AtomStates' being
#  assigned)


# VAMDC TAP dictionaries

RETURNABLES = {\
'NodeID':'sesam', # required
############################################################
'MethodID':'Method.id',
'MethodCategory':'Method.category',
############################################################
#Molecule
'MoleculeStoichiometricFormula':'Molecule.stoichiometric_formula',
'MoleculeOrdinaryStructuralFormula':'Molecule.ordinary_structural_formula',
'MoleculeChemicalName':'Molecule.chemical_name',
'MoleculeInchiKey':'Molecule.inchikey',
'MoleculeInchi':'Molecule.inchi',
'MoleculeSpeciesID':'Molecule.id',
'MoleculeIonCharge' : 'Molecule.charge',
# this is not an official VAMDC keyword
'MoleculeNumberOfAtoms' : 'Molecule.number_of_atoms',
############################################################
#Sources
'SourceID':'Source.id',
'SourceCategory':'Source.sourcecategory.value',
'SourceYear':'Source.year',
'SourceVolume':'Source.volume',
'SourceDOI':'Source.doi',
'SourceURI':'Source.uri',
'SourceAuthorName':'Source.authornames()',
############################################################
'RadTransID':'RadTran.id',
'RadTransWavelength':'RadTran.wavelength',
'RadTransWavelengthUnit':u'A',
'RadTransSpeciesRef':'RadTran.molecule.id',
'RadTransLowerStateRef':'RadTran.lowerstate.id',
'RadTransUpperStateRef':'RadTran.upperstate.id',
'RadTransProbabilityOscillatorStrength':'RadTran.oscillator_strength',
'RadTransWavenumber':'RadTran.getWavenumbers()',
'RadTransWavenumberMethod':'RadTran.getWavenumberMethods()',
'RadTransWavenumberComment':'RadTran.getWavenumberComments()',
'RadTransWavenumberUnit':'1/cm',
'RadTransProbabilityA' : 'RadTran.transition_probability',
'RadTransProbabilityAUnit' : '1/s',
'RadTransRefs' : 'RadTran.source.id',


############################################################
'MoleculeStateEnergy':'MoleculeState.energy',
'MoleculeStateEnergyOrigin':'MoleculeState.origin',
'MoleculeStateEnergyUnit':'1/cm',
'MoleculeStateID':'MoleculeState.id',
'MoleculeStateTotalStatisticalWeight':'MoleculeState.total_statistical_weight',
'MoleculeQnCase':'MoleculeState.SubCase.name',
'MoleculeQNElecStateLabel':'MoleculeState.Case.elec_state_label',
'MoleculeQNJ':'MoleculeState.Case.j',
'MoleculeQNF':'MoleculeState.Case.f',
'MoleculeQNr':'MoleculeState.Case.r',
'MoleculeQNparity':'MoleculeState.Case.parity',
#dcs,hundb
'MoleculeQNv':'MoleculeState.SubCase.v',
'MoleculeQNF1':'MoleculeState.SubCase.f1',
'MoleculeQNasSym':'MoleculeState.SubCase.as_sym',
'MoleculeQNelecInv':'MoleculeState.SubCase.elec_inv',
'MoleculeQNelecRefl':'MoleculeState.SubCase.elec_refl',
'MoleculeQNLambda':'MoleculeState.SubCase.lambda_field',
'MoleculeQNS':'MoleculeState.SubCase.s',
'MoleculeQNN':'MoleculeState.SubCase.n',
'MoleculeQNSpinComponentLabel':'MoleculeState.SubCase.spin_component_label',
'MoleculeQNF1':'MoleculeState.SubCase.f1',
'MoleculeQNKronigParity':'MoleculeState.SubCase.kronig_parity',
}

# The restrictable dictionary defines limitations to the search.
# The left-hand side is standardized, the righ-hand size should
# be defined in Django query-language style, where e.g. a search
# for the Species.atomic field  would be written as species__atomic.

RESTRICTABLES = {\
'MoleculeChemicalName':'molecule__chemical_name',
'MoleculeOrdinaryStructuralFormula': 'molecule__ordinary_structural_formula',
'MoleculeStoichiometricFormula':'molecule__stoichiometric_formula',
'RadTransWavelength':'wavelength',
'RadTransProbabilityOscillatorStrength':'oscillator_strength',
'StateEnergy':'lowerstate__energy',
'RadTransWavenumber':'wavenumber_calculated',
'InchiKey':'inchikey',
'Inchi':'inchi',
'lower.StateEnergy':'lowerstate__energy',
'upper.StateEnergy':'upperstate__energy',
'RadTransProbabilityA':'transition_probability',
'IonCharge' : 'molecule__charge',
'MoleculeMolecularWeight' : 'molecule__mass',
'MoleculeNumberOfAtoms': 'molecule__number_of_atoms',
}

# SLAP parameters
#
#    "SLAP_PARAMETER_NAME": {
#        "restrictable": "VamdcRestrictableName",
#        "convert": "coversion_function",
#        "isInterval" : True or False
#    }
SLAP_LINES_PARAMETERS = {\
    "WAVELENGTH": {
        "restrictable": "RadTransWavelength",
        "convert": "m2Angstr",
        "comment": "Wavelength in meter",
        "isInterval" : True,
        "unit" : "m"
    },
    "ION_CHARGE": {
        "restrictable": "IonCharge",
        "convert": None,
        "isInterval" : True   
    },
    "LOWER_LEVEL_ENERGY": {
        "restrictable": "lower.StateEnergy",
        "convert": "J2invcm",
        "comment": "Energy of lower level in Joules",
        "isInterval" : True,
        "unit":"J"
    },
    "UPPER_LEVEL_ENERGY": {
        "restrictable": "upper.StateEnergy",
        "convert": "J2invcm",
        "comment": "Energy of upper level in Joules",
        "isInterval" : True,
        "unit":"J"
    },
    "EINSTEINA": {
        "restrictable": "RadTransProbabilityA",
        "convert": None,
        "comment": "Transition probability in s-1",
        "isInterval" : True,
        "unit":"1/s"

    },

    "SPECIES_MASS": {
        "restrictable": "MoleculeMolecularWeight",
        "convert": None,
        "comment": "",
        "isInterval" : True,
        "unit" : "u"
    },

    #  restrictable can be a string or a list of strings
    "SPECIES": {
        "restrictable":["MoleculeChemicalName", "MoleculeOrdinaryStructuralFormula"],
        "comment":"",
        "isInterval" : False
    },   

    "INCHIKEY": {
        "restrictable":"InchiKey",
        "comment":"",
        "isInterval" : False
    },  

    # MAXREC is hard-coded in slapviews.py
    #"MAXREC": {},

    # not a standard SLAP parameter
    "WAVENUMBER": {
        "restrictable": "RadTransWavenumber",
        "convert": None,
        "comment": "Wavenumber in cm-1",
        "isInterval" : True,
        "unit":"1/cm"
        
    },
}

# Mapping dedicated to the species endpoint
SPECIES_ORM_FIELDS = {
    'InchiKey': 'inchikey',
    'MoleculeInchi': 'inchi',
    'MoleculeNumberOfAtoms': 'number_of_atoms',
    'MoleculeChemicalName': 'chemical_name',
    'MoleculeOrdinaryStructuralFormula': 'ordinary_structural_formula',
    'MoleculeStoichiometricFormula': 'stoichiometric_formula',
    # SLAP specific keyword
    'SpeciesType':'type'
}

# Dictionary of parameters in the SLAP species endpoint
#
#    "SPECIES_TYPE": {
#           "restrictable": "FieldInSpeciesOrmFields", 
#           "type":"pattern|interval"
#   }
SLAP_SPECIES_PARAMETERS = {
    "SPECIES_TYPE":           {"restrictable": "SpeciesType", 
                               "type":"pattern"},  
    "INCHIKEY":               {"restrictable": "InchiKey", 
                               "type":"exact"},
    "INCHI":                  {"restrictable": "MoleculeInchi", 
                               "type":"pattern",
                               "normalize": lambda v: v if v.startswith('InChI=') else 'InChI=' + v},
    "NUMBER_OF_ATOMS":        {"restrictable": "MoleculeNumberOfAtoms", 
                               "type":"interval"},
    "SPECIES":                {"restrictable": ["MoleculeChemicalName", "MoleculeOrdinaryStructuralFormula"], 
                               "type":"pattern"},
    "STOICHIOMETRIC_FORMULA": {"restrictable": "MoleculeStoichiometricFormula", 
                               "type":"pattern"},
}

PREFIXES = {\
#'lower.StateEnergy':'lowerstate__energy',
#'upper.StateEnergy':'upperstate__energy',
}

