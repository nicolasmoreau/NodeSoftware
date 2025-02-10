# coding: utf-8 -*-
import time
import logging
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

try:
    XSAMS_VERSION = RETURNABLES['XSAMSVersion']
except Exception as e:
    XSAMS_VERSION = '1.0'
try:
    SCHEMA_LOCATION = RETURNABLES['SchemaLocation']
except Exception as e:
    SCHEMA_LOCATION = 'http://vamdc.org/xml/xsams/%s' % XSAMS_VERSION

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

    def makeiter(obj, n=0):
        """
        Return an iterable of length n, no matter what.
        None as imput should give [], unless n!=0, then [None,None,...]
        """
        if not obj and obj != 0:
            # the empty case
            return [None] * n
        elif not isiterable(obj):
            if n:
                # return single value n times
                return [obj] * n
            else:
                return [obj]
        else:
            return obj

    def makeloop(keyword, G, *args):
        """
        Creates a nested list of lists. All arguments should be valid dictionary
        keywords and will be fed to G. They are expected to return iterables of equal lengths.
        The generator yields a list of current element of each argument-list in order, so one can do e.g.

           for name, unit in makeloop('TabulatedData', G, 'Name', 'Unit'):
              ...
        """
        if not args:
            return []
        Nargs = len(args)
        lis = []
        for arg in args:
            lis.append(makeiter(G("%s%s" % (keyword, arg))))
        try:
            Nlis = lis[0].count()
        except TypeError:
            Nlis = len(lis[0])
        olist = [[] for i in range(Nargs)]
        for i in range(Nlis):
            for k in range(Nargs):
                try:
                    olist[k].append(lis[k][i])
                except Exception:
                    olist[k].append("")
        return olist


def GetValue(returnable_key, **kwargs):
    """
    the function that gets a value out of the query set, using the global name
    and the node-specific dictionary.
    """
    # log.debug("getvalue, returnable_key : " + returnable_key)
    try:
        # obtain the RHS of the RETURNABLES dictionary
        name = RETURNABLES[returnable_key]
    except Exception as e:
        # The value is not in the dictionary for the node.  This is
        # fine.  Note that this is also used by if-clauses below since
        # the empty string evaluates as False.
        log.debug(e)
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
    result = {'WAVELENGTH': False,
              'ENERGY': False,
              'ELEMENT': False,
              'IONCHARGE': False,
              'INCHIKEY': False,
              "TERM": False,
              "CONFIGURATION": False,
              "STATE_DESCRIPTION": False,
              "EINSTEINA": False,
              "MOLECULARQNS": False}

    dictionary = set(RETURNABLES.keys())

    if 'RadTransWavelength' in dictionary:
        result['WAVELENGTH'] = True

    if len(list(set(['AtomStateEnergy', 'MoleculeStateEnergy']) &
                dictionary)) > 0:
        result['ENERGY'] = True

    if len(list(set(['AtomIonCharge', 'MoleculeIonCharge']) &
                dictionary)) > 0:
        result['IONCHARGE'] = True

    if len(list(set(['AtomSymbol', 'MoleculeChemicalName']) &
                dictionary)) > 0:
        result['ELEMENT'] = True

    if len(list(set(['AtomInchiKey', 'MoleculeInchiKey']) &
                dictionary)) > 0:
        result['INCHIKEY'] = True

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


def SlapSpecies(HeaderInfo=None, Sources=None, Methods=None, Functions=None,
                Environments=None, Atoms=None, Molecules=None,
                Solids=None, Particles=None, CollTrans=None, RadTrans=None,
                RadCross=None, NonRadTrans=None):
    """
    Return a VOTABLE containing the result of a select species request
    """
    yield (('<VOTABLE version="1.3" ' +
            '\nxmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" ' +
            '\nxmlns="http://www.ivoa.net/xml/VOTable/v1.3" ' +
            '\nxsi:schemaLocation="http://www.ivoa.net/xml/VOTable/v1.3 ' +
            'http://www.ivoa.net/xml/VOTable/VOTable-1.3.xsd"' +
            '\nxmlns:ssldm=' +
            '"http://www.ivoa.net/xml/SimpleSpectralLineDM/v2.0">\n' +
            '\t<RESOURCE type="results">\n' +
            '\t<INFO name="QUERY_STATUS" value="OK"/>\n' +
            '\t<INFO name="REQUEST_COMPLETED_TIMESTAMP" value="%s" />\n' +
            '\t<INFO name="SERVICE_VERSION" value="%s"/>\n' +
            '\t<INFO name="SERVICE_NAME" value="%s"/>\n' +
            '\t<TABLE>\n') % (int(time.time()),
                            settings.LAST_MODIFIED,
                            settings.NODENAME))

    fields = SpeciesTableFields()

    if fields['SPECIES_NAME'] is True:
        yield(FIELD_TABS)
        yield ('<FIELD ' +
               'name="SPECIES_NAME" datatype="char" ' +
               'arraysize="*" ucd="phys.atmol.element" ' +
               'utype="ssldm:Species.name" />\n')

    if fields['ION_CHARGE'] is True:
        yield(FIELD_TABS)
        yield ('<FIELD ' +
               ' name="ION_CHARGE" datatype="int" ' +
               ' ucd="phys.atmol.ionization" ' +
               ' utype="ssldm:Species.ionCharge" />\n')
    yield(FIELD_TABS)
    yield ('<FIELD ' +
           'name="SPECIES_TYPE" datatype="char" ' +
           'arraysize="*" utype="ssldm:Species.type"/>\n')

    if fields['INCHIKEY'] is True:
        yield(FIELD_TABS)
        yield ('<FIELD ' +
               ' name="INCHIKEY" datatype="char" ' +
               ' arraysize="*" utype="ssldm:Species.inChiKey" />\n')

    if fields['INCHI'] is True:
        yield(FIELD_TABS)
        yield ('<FIELD ' +
               ' name="INCHI" datatype="char" ' +
               ' arraysize="*" utype="ssldm:Species.inChi" />\n')
    yield(FIELD_TABS)
    yield '<DATA>\n\t\t\t<TABLEDATA>\n'

    if Atoms:
        G = lambda name: GetValue(name, Atom=Atom)
        for Atom in Atoms:
            yield(TR_TABS)
            yield('<TR>\n')
            if fields['SPECIES_NAME'] is True:
                yield(TD_TABS)
                yield('<TD>%s</TD>\n' % (G('AtomSymbol')))
            if fields['ION_CHARGE'] is True:
                yield(TD_TABS)
                yield('<TD>%s</TD>\n' % (G('AtomIonCharge')))
            yield(TD_TABS)
            yield('<TD>atom</TD>\n')
            if fields['INCHIKEY'] is True:
                yield(TD_TABS)
                yield('<TD>%s</TD>\n' % (G('AtomInchiKey')))
            if fields['INCHI'] is True:
                yield(TD_TABS)
                yield('<TD>%s</TD>\n' % (G('AtomInchi')))
            yield(TR_TABS)
            yield('</TR>\n')

    if Molecules:
        G = lambda name: GetValue(name, Molecule=Molecule)
        for Molecule in Molecules:
            yield(TR_TABS)
            yield '<TR>\n'
            if fields['SPECIES_NAME'] is True:
                try:
                    yield(TD_TABS)
                    yield '<TD>%s</TD>\n' % (MoleculeName(G, Molecule))
                except Exception as e:
                    yield(TD_TABS)
                    yield '<TD/>\n'
            if fields['ION_CHARGE'] is True:
                yield(TD_TABS)
                yield '<TD>%s</TD>\n' % (G('MoleculeIonCharge'))
            yield(TD_TABS)
            yield '<TD>molecule</TD>\n'
            if fields['INCHIKEY'] is True:
                yield(TD_TABS)
                yield '<TD>%s</TD>\n' % (G('MoleculeInchiKey'))
            if fields['INCHI'] is True:
                yield(TD_TABS)
                yield '<TD>%s</TD>\n' % (G('MoleculeInchi'))
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
                state['MoleculeIonCharge'] = H('MoleculeIonCharge')
                state['MoleculeInchiKey'] = H('MoleculeInchiKey')
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

        if isiterable(refs):
            for i in range(0, source_manager.sourceColumnCount):
                try:
                    if 'DigitalObjectIdentifier' in \
                        source_manager.sources[
                            SourceManager.getSourceIdentifier(refs[i])]:
                            result.append('<TD>%s</TD>' %
                                          (source_manager.sources[
                                           SourceManager.getSourceIdentifier(
                                               refs[i])]
                                           ['DigitalObjectIdentifier']))
                    elif 'UniformResourceIdentifier' in \
                         source_manager.sources[
                             SourceManager.getSourceIdentifier(refs[i])]:
                            result.append('<TD>%s</TD>' %
                                          (source_manager.sources
                                           [SourceManager.getSourceIdentifier(
                                            refs[i])]
                                           ['UniformResourceIdentifier']))

                # unused reference columns
                except Exception as e:
                    result.append('<TD></TD>')
        else:
            try:
                if 'DigitalObjectIdentifier' in \
                    source_manager.sources[
                        SourceManager.getSourceIdentifier(refs)]:
                    result.append('<TD>%s</TD>' %
                                  (source_manager.sources[
                                      SourceManager.getSourceIdentifier(refs)][
                                          'DigitalObjectIdentifier']))
                elif 'UniformResourceIdentifier' in \
                     source_manager.sources[
                         SourceManager.getSourceIdentifier(refs)]:
                    result.append('<TD>%s</TD>' %
                                  (source_manager.sources[
                                   SourceManager.getSourceIdentifier(refs)][
                                   'UniformResourceIdentifier']))

            except Exception as e:
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
        result.append('<TR>')
        if fields['WAVELENGTH']:
            result.append(TD_TABS)
            result.append('<TD>%s</TD>' %
                          convertWavelength(G, 'RadTransWavelength'))

        line_title = []

        if fields['ELEMENT']:
            line_title.append(states[G('RadTransUpperStateRef')]
                                    ['MoleculeChemicalName'])

        if fields['IONCHARGE']:
            line_title.append(" ion charge : %s" %
                              states[G('RadTransUpperStateRef')]
                                    ['MoleculeIonCharge'])

        if fields['ENERGY']:
            line_title.append(' Upper energy : %s , Lower energy : %s' %
                              (states[G('RadTransUpperStateRef')]
                                     ['MoleculeStateEnergy'],
                               states[G('RadTransLowerStateRef')]
                                     ['MoleculeStateEnergy']))
        result.append(TD_TABS)
        result.append('<TD>%s</TD>' % "".join(line_title))

        if fields['ENERGY']:
            result.append(TD_TABS)
            result.append('<TD>%s</TD>' %
                          (states[G('RadTransLowerStateRef')]
                                 ['MoleculeStateEnergy']))
            result.append(TD_TABS)
            result.append('<TD>%s</TD>' %
                          (states[G('RadTransUpperStateRef')]
                                 ['MoleculeStateEnergy']))

        if fields['CONFIGURATION'] or \
           fields['TERM'] or \
           fields['STATE_DESCRIPTION'] \
           or fields['MOLECULARQNS']:
            result.append(TD_TABS)
            result.append('<TD>%s %s</TD>' %
                          (states[G('RadTransLowerStateRef')]
                                 ['MoleculeStateDescription'],
                           states[G('RadTransLowerStateRef')]
                                 ['MoleculeStateQNLabel']))
            result.append(TD_TABS)
            result.append('<TD>%s %s</TD>' %
                          (states[G('RadTransUpperStateRef')]
                                 ['MoleculeStateDescription'],
                           states[G('RadTransUpperStateRef')]
                                 ['MoleculeStateQNLabel']))

        if fields['EINSTEINA']:
            result.append(TD_TABS)
            result.append('<TD>%s</TD>' % (G('RadTransProbabilityA')))

        if fields['ELEMENT']:
            result.append(TD_TABS)
            result.append('<TD>%s</TD>' %
                          (states[G('RadTransUpperStateRef')]
                                 ['MoleculeChemicalName']))

        if fields['IONCHARGE']:
            result.append(TD_TABS)
            result.append('<TD>%s</TD>' %
                          (states[G('RadTransUpperStateRef')]
                                 ['MoleculeIonCharge']))

        if fields['INCHIKEY']:
            result.append(TD_TABS)
            result.append('<TD>%s</TD>' %
                          (states[G('RadTransUpperStateRef')]
                                 ['MoleculeInchiKey']))

        result.extend(GetSourcesTds(G, source_manager))
        result.append(TR_TABS)
        result.append('</TR>')

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
            result.append('<TD>%s</TD>\n' %
                          (convertWavelength(G, 'RadTransWavelength')))
        else:
            # problematic case, how to manage all possible units ?
            # most cases handled with nm and A
            result.append(TD_TABS)
            result.append('<TD>%s</TD>\n' %
                          (G('RadTransWavelength')))

        line_title = []

        if fields['ELEMENT']:
            line_title.append(states[G('RadTransUpperStateRef')]['AtomSymbol'])

        if fields['IONCHARGE']:
            line_title.append(" ion charge : %s" %
                              states[G('RadTransUpperStateRef')]
                                    ['AtomIonCharge'])

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
                          (states[G('RadTransUpperStateRef')]
                                 ['AtomIonCharge']))

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


def SlapLines(HeaderInfo=None, Sources=None, Methods=None, Functions=None,
              Environments=None, Atoms=None, Molecules=None,
              Solids=None, Particles=None, CollTrans=None, RadTrans=None,
              RadCross=None, NonRadTrans=None, MAXREC=None):
    """
    Return a VOTABLE corresponding to an input query
    """
    source = SourceManager()

    if isiterable(Sources):
        source.initSources(Sources)
        source.initColumnCount(RadTrans, Atoms, Molecules)

    fields = LinesTableFields()
    returnables = RETURNABLES.keys()

    yield (('<VOTABLE version="1.3" ' +
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n' +
            'xmlns="http://www.ivoa.net/xml/VOTable/v1.3"\n' +
            'xsi:schemaLocation="http://www.ivoa.net/xml/VOTable/v1.3\n' +
            'http://www.ivoa.net/xml/VOTable/VOTable-1.3.xsd"\n' +
            'xmlns:ssldm="' +
            'http://www.ivoa.net/xml/SimpleSpectralLineDM/v2.0">\n' +
            '\t<RESOURCE type="results">\n' +
            '\t\t<INFO name="QUERY_STATUS" value="%s"/>\n' +
            '\t\t<INFO name="FILE_TIMESTAMP" value="%s" />\n' +
            '\t\t<INFO name="SERVICE_NAME" value="%s" />\n' +
            '\t\t<INFO name="SERVICE_VERSION" value="%s" />\n') %
           (getRequestStatus(MAXREC, HeaderInfo),
            int(time.time()),
            settings.NODENAME,
            settings.LAST_MODIFIED))
    yield('\t\t')
    yield('<TABLE>\n')

    yield(FIELD_TABS)
    yield('<FIELD ucd="em.wl" name="WAVELENGTH" ' +
          'utype="ssldm:Line.wavelength.value" ' +
          'datatype="double" unit="m"/>\n')
    yield(FIELD_TABS)
    yield('<FIELD ucd="meta.title" name="IDENTIFICATION" ' +
          'utype="ssldm:Line.title" datatype="char" ' +
          'arraysize="*"/>\n')

    if fields['ENERGY']:
        yield(FIELD_TABS)
        yield('<FIELD ucd="phys.energy;phys.atmol.level" ' +
              'name="LOWER_LEVEL_ENERGY" ' +
              'utype="ssldm:Line.lowerLevel.energy.value" ' +
              ' datatype="double" unit="J"/>\n')
        yield(FIELD_TABS)
        yield('<FIELD ucd="phys.energy;phys.atmol.level" ' +
              'name="UPPER_LEVEL_ENERGY" ' +
              'utype="ssldm:Line.upperLevel.energy.value" ' +
              'datatype="double" unit="J"/>\n')

    if fields['CONFIGURATION'] or \
       fields['TERM'] or \
       fields['STATE_DESCRIPTION'] or \
       fields['MOLECULARQNS']:
        yield(FIELD_TABS)
        yield('<FIELD ucd="phys.energy;phys.atmol.level" ' +
              'name="LOWER_LEVEL_NAME" ' +
              'utype="ssldm:Line.lowerLevel.name" ' +
              'datatype="char" arraysize="*"/>\n')
        yield(FIELD_TABS)
        yield('<FIELD ucd="phys.energy;phys.atmol.level" ' +
              'name="UPPER_LEVEL_NAME" ' +
              'utype="ssldm:Line.upperLevel.name" ' +
              'datatype="char" arraysize="*"/>\n')

    if fields['EINSTEINA']:
        yield(FIELD_TABS)
        yield('<FIELD ucd="phys.atmol.transProb" ' +
              'name="EINSTEIN_A" ' +
              'utype="ssldm:Line.einsteinA.value" ' +
              'datatype="double" unit="1/s" />\n')

    if fields['ELEMENT']:
        yield(FIELD_TABS)
        yield('<FIELD ucd="phys.atmol.element" ' +
              'name="LOWER_LEVEL_ELEMENT" ' +
              'utype="ssldm:Line.lowerLevel.element.name" ' +
              'datatype="char" arraysize="*"/>\n')

    if fields['IONCHARGE']:
        yield(FIELD_TABS)
        yield('<FIELD ucd="phys.atmol.ionization" ' +
              'name="LOWER_LEVEL_IONCHARGE" ' +
              'utype="ssldm:Line.lowerLevel.element.ionCharge" ' +
              'datatype="int" />\n')

    if fields['INCHIKEY']:
        yield(FIELD_TABS)
        yield('<FIELD ucd="phys.atmol.element" ' +
              'name="LOWER_LEVEL_ELEMENT_INCHIKEY" ' +
              'utype="ssldm:Line.lowerLevel.element.inChiKey" ' +
              'datatype="char" arraysize="*" />\n')

    # if fields['MOLECULARQNS']:
    #   yield '<FIELD name="LOWER_LEVEL_ELEMENT_INCHIKEY"
    #                 utype="ssldm:Line.lowerLevel.quantumState"
    #                 datatype="char" arraysize="*" />'
    #   yield '<FIELD name="UPPER_LEVEL_ELEMENT_INCHIKEY"
    #                 utype="ssldm:Line.upperLevel.quantumState"
    #                 datatype="char" arraysize="*" />'

    for i in range(0, source.sourceColumnCount):
        yield(FIELD_TABS)
        yield('<FIELD name="REFERENCE" ucd="meta.bib" ' +
              'datatype="char" arraysize="*" />\n')

    yield(FIELD_TABS)
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
