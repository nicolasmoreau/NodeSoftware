# coding: utf-8 -*-
import time
import logging
import xml.sax.saxutils as saxutils
from datetime import datetime, timezone
import six  # for python 2 and 3
#from collections import Iterable
from .unitconv import *


# Get the node-specific parts
from django.conf import settings
from importlib import import_module
from .generators import isiterable, makeiter
from requests.utils import CaseInsensitiveDict as CaselessDict

DICTS = import_module(settings.NODEPKG + '.dictionaries')
RETURNABLES = CaselessDict(DICTS.RETURNABLES)

# This must always be set.
try:
    NODEID = RETURNABLES['NodeID']
except Exception as e:
    NODEID = 'PleaseFillTheNodeID'

log = logging.getLogger('vamdc.tap.generator')

FIELD_TABS = '\t\t\t'
TR_TABS = FIELD_TABS + '\t\t'
TD_TABS = TR_TABS + '\t'


# Helper function to test if an object is a list or tuple

# isiterable = lambda obj: not isinstance(obj, six.string_types) \
#                 and isinstance(obj, Iterable)


def convertEnergy(G, keyword):
    if G(keyword + "Unit") == "1/cm":
        return invcm2J(G(keyword))
    elif G(keyword + "Unit") == "Ry":
        return Ry2J(G(keyword))
    else:
        raise Exception("Unknown energy unit")


def convertWavelength(G, keyword):
    if G(keyword + "Unit") == "A":
        return Angstr2m(G(keyword))
    elif G(keyword + "Unit") == "nm":
        return nm2m(G(keyword))
    else:
        raise Exception("Unknown energy unit")


def getRequestStatus(MAXREC, HeaderInfo):
    """
    Returns the status of the request :
    OVERFLOW if the result is truncated or MAXREC = 0
    ( cf DALI 1.1 section 3.4.4)
    OK if all the data are returned
    ERROR if there is no HeaderInfo
    """
    status = "OK"

    if HeaderInfo is None:
        return "ERROR"

    if MAXREC == 0:
        return "OVERFLOW"

    if "TRUNCATED" in HeaderInfo and HeaderInfo['TRUNCATED'] is not None:
        return "OVERFLOW"

    return status


class SourceManager(object):
    ''' object used to link sources to data
    '''
    def __init__(self):
        # dict of sources elements
        self.sources = {}
        # Returnable considered to find sources
        self.sourceReturnable = None
        # max number of sources for one element
        self.sourceColumnCount = 0
        self.__initSourceReturnable()

    def __initSourceReturnable(self):
        # where to look for source references
        if "RadTransRefs" in RETURNABLES:
            self.sourceReturnable = "RadTransRefs"

        elif "RadTransWavelengthRef" in RETURNABLES:
            self.sourceReturnable = "RadTransWavelengthRef"

        elif "RadTransWavenumberRef" in RETURNABLES:
            self.sourceReturnable = "RadTransWavenumberRef"

        elif "RadTransEnergyRef" in RETURNABLES:
            self.sourceReturnable = "RadTransEnergyRef"

        elif "AtomStateRef" in RETURNABLES:
            self.sourceReturnable = "AtomStateRef"

    def initColumnCount(self, RadTrans, Atoms, Molecules):
        """
          Set the returnable that will be used to read references
          and the max number of references for one transition or one level
        """
        maxsize = 0
        if RadTrans is not None:
            G = lambda name: GetValue(name, RadTran=RadTran)
            if self.sourceReturnable is not None:
                for RadTran in RadTrans:               
                    length = GetPropertyLength(G, self.sourceReturnable)
                    if length > maxsize:
                        maxsize = length

        elif Atoms is not None:
            G = lambda name: GetValue(name, State=State)
            if self.sourceReturnable is not None:
                for Atom in Atoms:
                    for State in Atom.States:
                        length = GetPropertyLength(G, self.sourceReturnable)
                        if length > maxsize:
                            maxsize = length

        # @note : no database available to test
        elif Molecules is not None:
            G = lambda name: GetValue(name, State=State)
            if self.sourceReturnable is not None:
                for Molecule in Molecules:
                    for Molecule in Molecule.States:
                        length = GetPropertyLength(G, self.sourceReturnable)
                        if length > maxsize:
                            maxsize = length

        self.sourceColumnCount = maxsize

    def initSources(self, Sources):
        """
          Return a dict of Source elements
          a Source element is a dict defining the following keys :
            DigitalObjectIdentifier, UniformResourceIdentifier, sourceID

          Each element in the result dict is indexed by its sourceID
        """
        result = {}
        G = lambda name: GetValue(name, Source=Source)
        for Source in Sources:
            source = {'DigitalObjectIdentifier': False,
                      'UniformResourceIdentifier': False,
                      'sourceID': False}
            source['sourceID'] = SourceManager.getSourceIdentifier(G('SourceID'))
            source['DigitalObjectIdentifier'] = GetValue('SourceDOI', Source=Source)
            source['UniformResourceIdentifier'] = GetValue('SourceURI', Source=Source)
            result[source['sourceID']] = source

        self.sources = result


    @staticmethod
    def getSourceIdentifier(sourceId):
        """
          Return a well-formatted identifier for a source element
        """
        return 'B%s-%s' % (NODEID, sourceId)

def GetValue(returnable_key, **kwargs):
    """
    the function that gets a value out of the query set, using the global name
    and the node-specific dictionary.
    """
    try:
        # obtain the RHS of the RETURNABLES dictionary
        name = RETURNABLES[returnable_key]
    except Exception as e:
        # The value is not in the dictionary for the node.  This is
        # fine.  Note that this is also used by if-clauses below since
        # the empty string evaluates as False.
        return ''

    if not name:
        # the key was in the dict, but the value was empty or None.
        return ''

    if '.' not in name:
        # No dot means it is a static string!
        return name

    # strip the prefix
    attribs = name.split('.')[1:]
    attribs.reverse()  # to later pop() from the front

    # get the current structure, throw away its name
    bla, obj = kwargs.popitem()

    # Go through the cascade of foreignKeys/attributes
    # to get to the leaf object
    while len(attribs) > 1:
        att = attribs.pop()
        obj = getattr(obj, att)

    # this is the last one now, can be either attribute or function
    att = attribs.pop()

    if att.endswith('()'):
        value = getattr(obj, att[:-2])()  # RUN IT!
    else:
        value = getattr(obj, att, name)

    if value is None:
        # the database returned NULL
        return ''
    elif value == 0:
        if isinstance(value, float):
            return '0.0'
        else:
            return '0'
    return value
    

def GetMolecularQuantumNumbers():
    """
    Return molecular QNs declared in the RETURNABLES list
    """
    result = []
    for value in RETURNABLES.keys():
        if value.startswith('MoleculeQN'):
            result.append(value)

    return result


def SpeciesTableFields():
    """
    Return a dict defining status of columns
    related to Species that could be added in the VOTABLE

    A key points to a boolean value to indicated if the field exists or
    not in the current node

    keys : SPECIES_NAME, ION_CHARGE, INCHIKEY, INCHI
    """
    result = {'SPECIES_NAME': False,
              'ION_CHARGE': False,
              'INCHIKEY': False,
              'INCHI': False}

    dictionary = set(RETURNABLES.keys())

    if len(list(set(['AtomSymbol',
                     'MoleculeChemicalName',
                     'MoleculeIUPACName',
                     'MoleculeStoichiometricFormula',
                     'MoleculeOrdinaryStructuralFormula']) & dictionary)) > 0:
        result['SPECIES_NAME'] = True

    if len(list(set(['AtomIonCharge', 'MoleculeIonCharge']) & dictionary)) > 0:
        result['ION_CHARGE'] = True

    if len(list(set(['AtomInchiKey', 'MoleculeInchiKey']) & dictionary)) > 0:
        result['INCHIKEY'] = True

    if len(list(set(['AtomInchi', 'MoleculeInchi']) & dictionary)) > 0:
        result['INCHI'] = True

    return result


def MoleculeName(G, Molecule):
    """
    Return the name of a molecule by searching in the varous RETURNABLEs
    that can define it

    Raise an error if no name defined
    """
    if 'MoleculeChemicalName' in RETURNABLES:
        return G('MoleculeChemicalName')

    if 'MoleculeIUPACName' in RETURNABLES:
        return G('MoleculeIUPACName')

    if 'MoleculeStoichiometricFormula' in RETURNABLES:
        return G('MoleculeStoichiometricFormula')

    if 'MoleculeOrdinaryStructuralFormula' in RETURNABLES:
        return G('MoleculeOrdinaryStructuralFormula')

    raise Error('No molecule name')


def LinesTableFields():
    """
    Return a dict defining status of columns
    related to Lines that could be added in the VOTABLE

    A key points to a boolean value to indicated if the field exists or
    not in the current node

    keys :  WAVELENGTH, ENERGY, ELEMENT, IONCHARGE,
            INCHIKEY, TERM, CONFIGURATION, STATE_DESCRIPTION
    """
    result = {
              'SPECIES' : False,
              'SPECIES_MASS' : False,
              'INCHI': False,
              'ION_CHARGE': False,
              'LOWER_LEVEL_ENERGY': False,
              'UPPER_LEVEL_ENERGY': False,
              "STATE_DESCRIPTION": False,
              "EINSTEINA": False
            }

    dictionary = set(RETURNABLES.keys())

    if len(list(set(['AtomSymbol', 'MoleculeChemicalName']) &
                dictionary)) > 0:
        result['ELEMENT'] = True

    if len(list(set(['AtomInchi', 'MoleculeInchi']) &
                dictionary)) > 0:
        result['INCHI'] = True

    if 'AtomStateConfigurationLabel' in dictionary:
        result['CONFIGURATION'] = True

    if 'AtomStateTermLabel' in dictionary:
        result['TERM'] = True

    if 'MoleculeStateDescription' in dictionary:
        result['STATE_DESCRIPTION'] = True

    if 'RadTransProbabilityA' in dictionary:
        result['EINSTEINA'] = True

    if(len(GetMolecularQuantumNumbers())) > 0:
        result['MOLECULARQNS'] = True

    return result


def SlapSpecies(SlapQuery=None, TapQuery=None, HeaderInfo=None, Sources=None, Methods=None, Functions=None,
                Environments=None, Atoms=None, Molecules=None,
                Solids=None, Particles=None, CollTrans=None, RadTrans=None,
                RadCross=None, NonRadTrans=None, MAXREC=None):
    """
    Return a VOTABLE containing the result of a select species request
    """

    log.debug("SlapSpecies")
    log.debug(TapQuery)

    if HeaderInfo is None:
        HeaderInfo = {}

    yield (('<VOTABLE version="1.5" '
            '\nxmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            '\nxmlns="http://www.ivoa.net/xml/VOTable/v1.3" '
            '\nxsi:schemaLocation="http://www.ivoa.net/xml/VOTable/v1.3 '
            'http://www.ivoa.net/xml/VOTable/votable-1.5.xsd">\n'
            '\t<RESOURCE type="results">\n'
            f'\t\t<INFO name="QUERY_STATUS" value="{getRequestStatus(MAXREC, HeaderInfo)}"/>\n'
            f'\t\t<INFO name="request_date" value="{datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")}" />\n'
            f'\t\t<INFO name="request" value="{saxutils.escape(SlapQuery)}" />\n'
            '\t\t<INFO name="service_protocol" value="ivo://ivoa.net/std/SLAP#species-2.0" />\n' 
            f'\t\t<INFO name="last_update_date" value="{settings.LAST_MODIFIED}" />\n' 
            f'\t\t<INFO name="publisher" value="" />\n'
            '\t<TABLE>\n'))
    
    fields = SpeciesTableFields()

    yield(FIELD_TABS)
    yield (('<FIELD '
            'name="species_name" datatype="char" ' 
            'arraysize="*" ucd="phys.atmol.element" >\n'))

    #if fields['ION_CHARGE'] is True:
    yield(FIELD_TABS)
    yield (('<FIELD ' 
            ' name="ion_charge" datatype="int" '
            ' ucd="phys.atmol.ionization"  />\n'))
    
    yield(FIELD_TABS)
    yield (('<FIELD ' 
           'name="species_type" datatype="char" ' 
           'arraysize="*"/>\n'))
    
    yield(FIELD_TABS)
    yield (('<FIELD '
            ' name="inchikey" datatype="char" ' 
            ' arraysize="*" />\n'))

    yield(FIELD_TABS)
    yield (('<FIELD '
            ' name="inchi" datatype="char" ' 
            ' arraysize="*" />\n'))
    
    yield(FIELD_TABS)
    yield (('<FIELD '
            ' name="species_stoichiometric_formula" datatype="char" ' 
            ' arraysize="*" />\n'))
    yield(FIELD_TABS)
    yield (('<FIELD '
            ' name="number_of_atoms" datatype="int" />\n'))
    yield(FIELD_TABS)
    yield '<DATA>\n\t\t\t<TABLEDATA>\n'

    if MAXREC is None or MAXREC > 0:
        if Atoms:
            G = lambda name: GetValue(name, Atom=Atom)
            for Atom in Atoms:
                yield(TR_TABS)
                yield('<TR>\n')
                yield(TD_TABS)
                yield(f'<TD>{G("AtomSymbol")}</TD>\n')
                if fields['ION_CHARGE'] is True:
                    yield(TD_TABS)
                    yield(f'<TD>{G("AtomIonCharge")}</TD>\n')
                else:
                    yield(TD_TABS)
                    yield('<TD>0</TD>\n')
                yield(TD_TABS)
                yield('<TD>atom</TD>\n')
                yield(TD_TABS)
                yield(f'<TD>{G("AtomInchiKey")}</TD>\n')
                yield(TD_TABS)
                yield(f'<TD>{G("AtomInchi")}</TD>\n')
                yield(TD_TABS)
                yield('<TD>NULL</TD>\n')
                yield(TR_TABS)
                yield('</TR>\n')

        if Molecules:
            G = lambda name: GetValue(name, Molecule=Molecule)
            for Molecule in Molecules:
                yield(TR_TABS)
                yield '<TR>\n'
                yield(TD_TABS)
                yield f'<TD>{MoleculeName(G, Molecule)}</TD>\n'
                if fields['ION_CHARGE'] is True:
                    yield(TD_TABS)
                    yield f'<TD>{G("MoleculeIonCharge")}</TD>\n'
                else:
                    yield(TD_TABS)
                    yield('<TD>0</TD>\n')
                yield(TD_TABS)
                yield '<TD>molecule</TD>\n'
                yield(TD_TABS)
                yield f'<TD>{G("MoleculeInchiKey")}</TD>\n'
                yield(TD_TABS)
                yield f'<TD>{G("MoleculeInchi")}</TD>\n'
                yield(TD_TABS)
                yield f'<TD>{G("MoleculeStoichiometricFormula")}</TD>\n'
                yield(TD_TABS)
                yield f'<TD>{G("MoleculeNumberOfAtoms")}</TD>\n'
                yield(TR_TABS)
                yield '</TR>\n'
    yield ('\t\t\t\t</TABLEDATA>\n' +
           '\t\t\t</DATA>\n' +
           '\t\t</TABLE>\n' +
           '\t</RESOURCE>\n' +
           '</VOTABLE>')


def GetMolecularStates(Molecules):
    """
    Return a dict of molecular states indexed by MoleculeStateID
    """
    G = lambda name: GetValue(name, State=State)
    H = lambda name: GetValue(name, Molecule=Molecule)
    result = {}
    for Molecule in Molecules:
        try:
            for State in Molecule.States:
                state = {}
                state["MoleculeStateID"] = G('MoleculeStateID')
                state['MoleculeChemicalName'] = H('MoleculeChemicalName')
                state['MoleculeOrdinaryStructuralFormula'] = H('MoleculeOrdinaryStructuralFormula')
                if H('MoleculeIonCharge') != '':
                    state['MoleculeIonCharge'] = H('MoleculeIonCharge')
                else: 
                    state['MoleculeIonCharge'] = 0
                state['MoleculeInchiKey'] = H('MoleculeInchiKey')
                state['MoleculeInchi'] = H('MoleculeInchi')
                state['MoleculeMolecularWeight'] = H('MoleculeMolecularWeight')
                state['MoleculeStateDescription'] = G('MoleculeStateDescription')
                state['MoleculeStateEnergy'] = convertEnergy(G, 'MoleculeStateEnergy')

                qns = GetMolecularQuantumNumbers()
                qn_label_string = ""
                for qn in qns:
                    value = G(qn)
                    if value != "":
                        qn_label_string += ' %s=%s ' % \
                            (qn.replace('MoleculeQN', ''), value)

                state['MoleculeStateQNLabel'] = qn_label_string

                result[state["MoleculeStateID"]] = state

        except AttributeError as e:
            print(e)
    return result


def GetAtomicStates(Atoms):
    """
    Return a dict of atomic states indexed by AtomStateID
    """
    G = lambda name: GetValue(name, State=State)
    H = lambda name: GetValue(name, Atom=Atom)
    I = lambda name: GetValue(name, Component=Component)

    result = {}
    for Atom in Atoms:
        try:
            for State in Atom.States:
                state = {}
                state["AtomStateID"] = G('AtomStateID')
                if 'AtomStateEnergy' in RETURNABLES:
                    state['AtomStateEnergy'] = \
                        convertEnergy(G, 'AtomStateEnergy')
                state['AtomSymbol'] = H('AtomSymbol')
                state['AtomIonCharge'] = H('AtomIonCharge')
                state['AtomInchiKey'] = H('AtomInchiKey')

                configuration = []
                term = []

                for Component in makeiter(State.Components):
                    configuration.append(I('AtomStateConfigurationLabel'))
                    configuration.append(I('AtomStateTermLabel'))

                state['AtomStateConfigurationLabel'] = ' '.join(configuration)
                state['AtomStateTermLabel'] = ' '.join(term)

                result[state["AtomStateID"]] = state
        except AttributeError as e:
            print(e)
    return result


def GetSourcesTds(G, source_manager):
    """
    Return a list of TD elements to be inserted into a VOTABLE
    Each TD is the URL or the DOI of a reference
    """
    result = []
    if source_manager.sourceReturnable is not None:
        refs = G(source_manager.sourceReturnable)
        refs_list = refs if isiterable(refs) else [refs]

        for i in range(0, source_manager.sourceColumnCount):
            try:
                if 'DigitalObjectIdentifier' in \
                    source_manager.sources[
                        SourceManager.getSourceIdentifier(refs_list[i])]:
                        value = source_manager.sources[SourceManager.getSourceIdentifier(refs_list[i])] \
                                                      ['DigitalObjectIdentifier']
                        result.append(TD_TABS)
                        result.append(f'<TD>{value}</TD>\n')
                if 'UniformResourceIdentifier' in \
                        source_manager.sources[
                            SourceManager.getSourceIdentifier(refs_list[i])]:
                        value = (source_manager.sources[SourceManager.getSourceIdentifier(refs_list[i])] \
                                                       ['UniformResourceIdentifier'])
                        result.append(TD_TABS)
                        result.append(f'<TD>{value}</TD>\n')

            # unused reference columns
            except Exception as e:
                result.append(TD_TABS)
                result.append('<TD></TD>')

    return result


def TableMolecularTrs(RadTrans, states, fields, source_manager):
    """
    Return a list of TR elements to be inserted into a VOTABLE for molecular
    data
    """
    result = []
    G = lambda name: GetValue(name, RadTran=RadTran)
    for RadTran in RadTrans:
        result.append(TR_TABS)
        result.append('<TR>\n')
        result.append(TD_TABS)
        result.append(f'<TD>{convertWavelength(G, 'RadTransWavelength')}</TD>\n')
        result.append(TD_TABS)
        result.append(f'<TD>NULL</TD>\n')
        line_title = []
        lower_ref = G('RadTransLowerStateRef')
        upper_ref = G('RadTransUpperStateRef')
        line_title.append((f' {states[lower_ref]['MoleculeOrdinaryStructuralFormula']} '))
        line_title.append(states[lower_ref]['MoleculeStateQNLabel'])
        line_title.append(' -> ')
        line_title.append(states[upper_ref]['MoleculeStateQNLabel'])
        result.append(TD_TABS)
        result.append(f'<TD>{"".join(line_title)}</TD>\n')
        result.append(TD_TABS)
        result.append(f'<TD>{states[lower_ref]['MoleculeChemicalName']}</TD>\n')
        result.append(TD_TABS)
        result.append(f'<TD>{states[lower_ref]['MoleculeMolecularWeight']}</TD>\n')
        result.append(TD_TABS)
        result.append(f'<TD>{states[lower_ref]['MoleculeInchiKey']}</TD>\n')
        result.append(TD_TABS)
        if fields['INCHI']:
            result.append(f'<TD>{states[lower_ref]['MoleculeInchi']}</TD>\n')
        result.append(TD_TABS)
        result.append(f'<TD>{states[lower_ref]['MoleculeIonCharge']}</TD>\n')
        result.append(TD_TABS)
        result.append(f'<TD>{states[lower_ref]['MoleculeStateQNLabel']}</TD>\n')
        result.append(TD_TABS)
        result.append(f'<TD>{states[upper_ref]['MoleculeStateQNLabel']}</TD>\n')
        if fields['EINSTEINA']:
            result.append(TD_TABS)
            result.append(f'<TD>{G('RadTransProbabilityA')}</TD>\n')

        result.append(TD_TABS)
        result.append(f'<TD>{states[lower_ref]['MoleculeStateEnergy']}</TD>\n')
        result.append(TD_TABS)
        result.append(f'<TD>{states[upper_ref]['MoleculeStateEnergy']}</TD>\n')        
        result.extend(GetSourcesTds(G, source_manager))
        result.append(TR_TABS)
        result.append('</TR>\n')

    return ''.join(result)


def TableAtomicTrs(RadTrans, states, fields, source_manager):
    """
    Return a list of TR elements to be inserted into a VOTABLE for atomic
    data
    """
    result = []
    G = lambda name: GetValue(name, RadTran=RadTran)
    for RadTran in RadTrans:
        result.append(TR_TABS)
        result.append('<TR>\n')
        if fields['WAVELENGTH']:
            result.append(TD_TABS)
            result.append(f'<TD>{convertWavelength(G, 'RadTransWavelength')}</TD>\n')
        else:
            # problematic case, how to manage all possible units ?
            # most cases handled with nm and A
            result.append(TD_TABS)
            result.append('<TD>%s</TD>\n' %
                          (G('RadTransWavelength')))

        line_title = []

        if fields['ELEMENT']:
            line_title.append(states[G('RadTransLowerStateRef')]['AtomSymbol'])
            line_title.append(states[G('RadTransUpperStateRef')]['AtomSymbol'])

        if fields['IONCHARGE']:
            line_title.append(" lower level ion charge : %s" %
                              states[G('RadTransLowerStateRef')]
                                    ['AtomIonCharge'])
            line_title.append(" upper level ion charge : %s" %
                              states[G('RadTransUpperStateRef')]
                                    ['AtomIonCharge'])
        else:
            line_title.append(" lower level ion charge : 0")
            line_title.append(" upper level ion charge : 0")           
            

        if fields['ENERGY']:
            line_title.append(' Upper energy : %s , Lower energy : %s' %
                              (states[G('RadTransUpperStateRef')]
                                     ['AtomStateEnergy'],
                               states[G('RadTransLowerStateRef')]
                                     ['AtomStateEnergy']))
        result.append(TD_TABS)
        result.append('<TD>%s</TD>\n' % (''.join(line_title)))

        if fields['ENERGY']:
            result.append(TD_TABS)
            result.append('<TD>%s</TD>\n' %
                          (states[G('RadTransLowerStateRef')]
                                 ['AtomStateEnergy']))
            result.append(TD_TABS)
            result.append('<TD>%s</TD>\n' %
                          (states[G('RadTransUpperStateRef')]
                                 ['AtomStateEnergy']))

        if fields['CONFIGURATION'] or \
           fields['TERM'] or \
           fields['STATE_DESCRIPTION']:
            result.append(TD_TABS)
            result.append('<TD>%s %s</TD>\n' %
                          ((states[G('RadTransLowerStateRef')]
                                  ['AtomStateConfigurationLabel']),
                           states[G('RadTransLowerStateRef')]
                                 ['AtomStateTermLabel']))
            result.append(TD_TABS)
            result.append('<TD>%s %s</TD>\n' %
                          ((states[G('RadTransUpperStateRef')]
                                  ['AtomStateConfigurationLabel']),
                           states[G('RadTransUpperStateRef')]
                                 ['AtomStateTermLabel']))

        if fields['EINSTEINA']:
            result.append(TD_TABS)
            result.append('<TD>%s</TD>\n' % (G('RadTransProbabilityA')))

        if fields['ELEMENT']:
            result.append(TD_TABS)
            result.append('<TD>%s</TD>\n' %
                          (states[G('RadTransUpperStateRef')]['AtomSymbol']))

        if fields['IONCHARGE']:
            result.append(TD_TABS)
            result.append('<TD>%s</TD>\n' %
                          (states[G('RadTransLowerStateRef')]
                                 ['AtomIonCharge']))
            result.append('<TD>%s</TD>\n' %
                          (states[G('RadTransUpperStateRef')]
                                 ['AtomIonCharge']))
        else:
            result.append(TD_TABS)
            result.append('<TD>0</TD>\n')
            result.append('<TD>0</TD>\n')
            
        if fields['INCHIKEY']:
            result.append(TD_TABS)
            result.append('<TD>%s</TD>\n' %
                          (states[G('RadTransUpperStateRef')]
                                 ['AtomInchiKey']))

        result.extend(GetSourcesTds(G, source_manager))
        result.append(TR_TABS)
        result.append('</TR>\n')

    return ''.join(result)


def GetPropertyLength(G, prop):
    """
    Return length of an iterable pointed by a RETURNABLE
    Return 1 if the property is not iterable
    """
    values = G(prop)
    length = 1
    if isiterable(values):
        length = len(values)
    return length


def SlapLines(SlapQuery=None, TapQuery=None, HeaderInfo=None, Sources=None,
              Environments=None, Atoms=None, Molecules=None, Methods = None,
              RadTrans=None, MAXREC=None):
    """
    Return a VOTABLE corresponding to an input query
    """
    source = SourceManager()

    if isiterable(Sources):
        source.initSources(Sources)
        source.initColumnCount(RadTrans, Atoms, Molecules)

    fields = LinesTableFields()
    returnables = RETURNABLES.keys()

    yield ((f'<VOTABLE version="1.5" '
            f'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n'
            f'xmlns="http://www.ivoa.net/xml/VOTable/v1.3"\n'
            f'xsi:schemaLocation="http://www.ivoa.net/xml/VOTable/v1.3\n'
            f'http://www.ivoa.net/xml/VOTable/votable-1.5.xsd">\n'
            f'\t<RESOURCE type="results">\n' 
            f'\t\t<INFO name="QUERY_STATUS" value="{getRequestStatus(MAXREC, HeaderInfo)}"/>\n' 
            f'\t\t<INFO name="request_date" value="{datetime.now(timezone.utc)}" />\n'
            f'\t\t<INFO name="request" value="{saxutils.escape(SlapQuery)}" />\n'
            f'\t\t<INFO name="service_ivoid" value="{getattr(settings, "SERVICE_IVOID", "")}"/>\n'
            f'\t\t<INFO name="query" value="{saxutils.escape(" ".join(TapQuery.split()), {'"': '&quot;'})}" />\n'
            f'\t\t<INFO name="service_protocol" value="ivo://ivoa.net/std/SLAP#lines-2.0" />\n' 
            f'\t\t<INFO name="last_update_date" value="{settings.LAST_MODIFIED}" />\n' 
            f'\t\t<INFO name="publisher" value="" />\n'))
    yield('\t\t')
    yield('<TABLE>\n')

    yield(FIELD_TABS)
    yield('<FIELD ucd="em.wl" name="vacuum_wavelength" ' +
           'datatype="double" unit="m"/>\n')
    yield(FIELD_TABS)
    yield('<FIELD ucd="stat.error;em.wl" name="vacuum_wavelength_error" ' +
           'datatype="double" unit="m"/>\n')
    yield(FIELD_TABS)
    yield('<FIELD ucd="meta.title" name="line_title" ' +
          ' datatype="char" arraysize="*"/>\n')
    yield(FIELD_TABS)
    yield('<FIELD ucd="phys.atmol.element" name="species_name" ' +
          ' datatype="char" arraysize="*"/>\n')
    yield(FIELD_TABS)
    yield('<FIELD ucd="phys.mass" name="species_mass" ' +
          ' datatype="float"/>\n')
    yield(FIELD_TABS)
    yield('<FIELD ucd="phys.atmol.element" name="inchikey" ' +
          ' datatype="char" arraysize="*"/>\n')
    yield(FIELD_TABS)
    yield('<FIELD ucd="phys.atmol.element" name="inchi" ' +
          ' datatype="char" arraysize="*"/>\n')
    yield(FIELD_TABS)
    yield('<FIELD ucd="phys.atmol.element;phys.atmol.ionization" name="ion_charge" ' +
          ' datatype="int" />\n')
    
    yield(FIELD_TABS)
    yield('<FIELD ucd="meta.title;phys.atmol.level" name="lower_level_description" ' +
          ' datatype="char" arraysize="*"/>\n')
    yield(FIELD_TABS)
    yield('<FIELD ucd="meta.title;phys.atmol.level" name="upper_level_description" ' +
          ' datatype="char" arraysize="*"/>\n')
    yield(FIELD_TABS)
    yield('<FIELD ucd="phys.atmol.transProb" name="einstein_a" ' +
          ' datatype="double" unit="1/s"/>\n')
    yield(FIELD_TABS)
    yield('<FIELD ucd="phys.energy;phys.atmol.level" name="lower_level_energy" ' +
          ' datatype="double" unit="J"/>\n')
    yield(FIELD_TABS)
    yield('<FIELD ucd="phys.energy;phys.atmol.level" name="upper_level_energy" ' +
          ' datatype="double" unit="J"/>\n')

    for i in range(source.sourceColumnCount):
        yield(FIELD_TABS)
        yield('<FIELD ucd="meta.ref.doi" name="reference_doi" ' +
            ' datatype="char" arraysize="*"/>\n')
        
        yield(FIELD_TABS)
        yield('<FIELD ucd="meta.ref.uri" name="reference_uri" ' +
            ' datatype="char" arraysize="*"/>\n')

    yield(FIELD_TABS)
    if isiterable(Molecules) is True or isiterable(Atoms) is True:
        yield('<DATA>\n')
        yield('\t\t\t\t')
        yield('<TABLEDATA>\n')

        # molecular states
        if MAXREC is None or MAXREC > 0:
            if isiterable(Molecules):
                states = GetMolecularStates(Molecules)
                yield TableMolecularTrs(RadTrans, states, fields, source)

            if isiterable(Atoms):
                states = GetAtomicStates(Atoms)
                yield TableAtomicTrs(RadTrans, states, fields, source)

        yield('\t\t\t\t')
        yield('</TABLEDATA>\n')
        yield('\t\t\t')
        yield('</DATA>\n')
    yield('\t\t')
    yield('</TABLE>\n')
    yield('\t')
    yield('</RESOURCE>\n')
    yield('</VOTABLE>')

