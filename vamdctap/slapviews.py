# -*- coding: utf-8 -*-
from django.shortcuts import render
from django.http import HttpResponse, StreamingHttpResponse
import traceback
import logging
import os
import math
from base64 import b64encode
from django.conf import settings
from importlib import import_module
from requests.utils import CaseInsensitiveDict as CaselessDict
from .views import tapServerError, dbConnected
from .unitconv import *
from .slapgenerators import *
from .sqlparse import SQL


randStr = lambda n: b64encode(os.urandom(int(math.ceil(0.75*n))))[:n]


log = logging.getLogger('vamdc.tap')


# if settings.QUERY_STORE_ACTIVE:
#     try:
#         import requests as librequests
#     except:
#         log.critical('settings.QUERY_STORE_ACTIVE is True but requests package is missing!')

QUERYFUNC = import_module(settings.NODEPKG+'.queryfunc')
DICTS = import_module(settings.NODEPKG+'.dictionaries')
RESTRICTABLES = CaselessDict(DICTS.RESTRICTABLES)
RETURNABLES = CaselessDict(DICTS.RETURNABLES)
SLAP_PARAMETERS = CaselessDict(DICTS.SLAP_PARAMETERS)

# import helper modules that reside in the same directory
NODEID = CaselessDict(DICTS.RETURNABLES)['NodeID']


class SLAPQUERY(object):
    """
    This class holds the query, does some validation
    and triggers the SQL parser.
    """    
    LINES_REQUEST = "lines"
    SPECIES_REQUEST = "species"    

    def __init__(self, request, request_type):
        """
        Build a SLAPQUERY object
        request : django request object
        request_type : LINES_REQUEST or SPECIES_REQUEST
        """
        # if 'X_REQUEST_METHOD' in request.META: # workaround for mod_wsgicol
        #   self.XRequestMethod = request.META['X_REQUEST_METHOD']
        print("SLAPQUERY 1")
        self.HTTPmethod = request.method
        self.isvalid = True
        self.errormsg = ''
        # self.token = request.token
        print("SLAPQUERY 2")
        try :
            self.checkSlapParameters(request)
        except Exception as e:
            print(e)
            traceback.print_exc()
            log.debug(self.errormsg)
            self.isvalid = False
            self.errormsg = e
            raise e

        try:
            # build a tap request from SLAP parameters
            print("SLAPQUERY 3")
            tap_request = self.getTapRequestObject(CaselessDict(dict(request.GET or request.POST)), request_type)
            self.request = tap_request

        except Exception as e:
            print("SLAPQUERY 4")
            print(e)
            traceback.print_exc()
            log.debug(self.errormsg)
            self.isvalid = False
            self.errormsg = 'Could not read argument dict: %s' % e
            raise e

        print("SLAPQUERY 5")
        if self.isvalid:
            self.validate()

        try : 
            print("SLAPQUERY 6")
            self.fullurl = getBaseURL(request, base="slap") + \
                'sync?' + \
                request.META.get('QUERY_STRING')
        except Exception as e:
            print("SLAPQUERY 7")
            print(e)
            traceback.print_exc() 

    def validate(self):
        try:
            self.lang = self.request['LANG'][0]
            self.lang = self.lang.lower()
        except Exception as e:
            log.debug('LANG is empty, assuming VSS2')
            log.debug(e)
            self.lang = 'vss2'
        else:
            if self.lang not in ('vss1', 'vss2'):
                self.errormsg += 'Only LANG=VSS1 or LANG=VSS2 is supported.\n'

        try:
            self.query = self.request['QUERY']
        except Exception as e:
            self.errormsg += 'Cannot find QUERY in request.\n'
            log.debug(e)

        try:
            self.format = self.request['FORMAT'][0]
            self.format = self.format.lower()
        except Exception as e:
            log.debug('FORMAT is empty, assuming XSAMS')
            log.debug(e)
            self.format = 'xsams'
        else:
            if self.format != 'xsams':
                log.debug('Requested FORMAT is not XSAMS, letting it pass anyway.')

        try:
            self.parsedSQL = SQL.parseString(self.query, parseAll=True)
        # if this fails, we're done
        except Exception as e:
            log.debug(e)
            self.errormsg += 'Could not parse the SQL query string: %s\n' % \
                             getattr(self, 'query', None)
            self.isvalid = False
            return

        self.where = self.parsedSQL.where        

        if self.errormsg:
            self.isvalid = False

    def getTapRequestObject(self, request, request_type):
        """
        Return a VAMDC-TAP request equivalent to the parameters
        received in the SLAP one
        """
        result = request.copy()
        if request_type is SLAPQUERY.LINES_REQUEST:
            try:
                tap = self.paramsToTap(request)
                result.update({u'LANG': [u'VSS2'],
                               u'QUERY': tap,
                               u'REQUEST': [u'doQuery'],
                               u'FORMAT': [u'XSAMS']})
            except Exception as e:
                raise e
        elif request_type is SLAPQUERY.SPECIES_REQUEST:
            result.update({u'LANG': [u'VSS2'],
                           u'QUERY': u'select species',
                           u'REQUEST': [u'doQuery'],
                           u'FORMAT': [u'XSAMS']})
        else:
            raise Error("Unknown query type for SLAP service")
        return result

    def buildInterval(self, keyword, interval, convert):
        """
        Return a SLAP-compatible interval representation
        keyword : name of a restrictable
        interval : list of values in ascendant order
        convert : conversion function
        """
        result = ''
        if len(interval) == 2:
            if interval[0] == "-Inf":
                result += ' %s <= %s' % (keyword, convert(interval[1]))
            elif interval[1] == "+Inf":
                result += ' %s >= %s ' % (keyword, convert(interval[0]))
            else:
                result += ' ( %s >= %s and %s <= %s ) ' %\
                          (keyword, convert(interval[0]),
                           keyword, convert(interval[1]))
        if len(interval) == 1:
            result += ' %s = %s ' % (keyword, convert(interval[0]))
        return result
    
    def checkSlapParameters(self, request):
        """ Return True is all the parameters are valid, 
            raise an exception if this is not the case

        """
        slap_params = request.GET.dict()     
        for param in slap_params:
            if param not in SLAP_PARAMETERS:
                raise Exception("{} is not a valid SLAP parameters".format(param))
        return True

    def paramsToTap(self, request):
        """
        Converts SLAP parameters into a VAMDC-TAP request
        """
        where = []
        # slap parameter names are case insensitive
        slap_params = request

        if 'WAVELENGTH' in slap_params:
            # WAVELENGTH is mandatory in SLAP specifications
            wavelengths = slap_params['WAVELENGTH'][0].split()
            if len(wavelengths) == 2:
                if wavelengths[0] == "-Inf":
                    where.append(' ( RadTransWavelength <= %s ) ' %
                                 str(m2Angstr(wavelengths[1])))
                elif wavelengths[1] == "+Inf":
                    where.append(' ( RadTransWavelength >= %s ) ' %
                                 str(m2Angstr(wavelengths[0])))
                else:
                    where.append(' ( RadTransWavelength >= %s and\
                                     RadTransWavelength <= %s ) ' %
                                 (str(m2Angstr(wavelengths[0])),
                                  str(m2Angstr(wavelengths[1]))))
            if len(wavelengths) == 1:
                where.append(' ( RadTransWavelength = %s )' %
                             str(m2Angstr(wavelengths[0])))

        if 'ION_CHARGE' in slap_params:
            charges = slap_params['ION_CHARGE'][0].split()
            if len(charges) == 2:
                if charges[0] == "-Inf":
                    where.append(' ( IonCharge <= %s ) ' %
                                 str(charges[1]))
                elif charges[1] == "+Inf":
                    where.append(' ( IonCharge >= %s ) ' %
                                 str(charges[0]))
                else:
                    where.append(' ( IonCharge >= %s and\
                                     IonCharge <= %s ) ' %
                                 (str(charges[0]),
                                  str(charges[1])))
            if len(charges) == 1:
                where.append(' ( IonCharge = %s )' %
                             str(charges[0]))

        if 'CHEMICAL_ELEMENT' in slap_params:
            elements = slap_params['CHEMICAL_ELEMENT']
            for element in elements:
                if "AtomSymbol" in RESTRICTABLES:
                    where.append(' AtomSymbol = "%s"' % element)
                if 'MoleculeChemicalName' in RESTRICTABLES:
                    where.append(' MoleculeChemicalName = "%s"' % element)

        if 'LOWER_LEVEL_ENERGY' in slap_params and \
           'lower.stateenergy' in RESTRICTABLES:
            energies = slap_params['LOWER_LEVEL_ENERGY'][0].split()
            if len(energies) == 2:
                if energies[0] == "-Inf":
                    where.append(' ( lower.StateEnergy <= %s ) ' %
                                 str(J2invcm(energies[1])))
                elif energies[1] == "+Inf":
                    where.append(' ( lower.StateEnergy >= %s ) ' %
                                 str(J2invcm(energies[0])))
                else:
                    where.append(' ( lower.StateEnergy >= %s and \
                                 lower.StateEnergy <= %s ) ' %
                                 (str(J2invcm(energies[0])),
                                  str(J2invcm(energies[1]))))
            if len(energies) == 1:
                where.append(' ( lower.StateEnergy = %s )' %
                             str(J2invcm(energies[0])))

        if 'UPPER_LEVEL_ENERGY' in slap_params and \
           'upper.stateenergy' in RESTRICTABLES:
            energies = slap_params['UPPER_LEVEL_ENERGY'][0].split()

            if len(energies) == 2:
                if energies[0] == "-Inf":
                    where.append(' ( upper.StateEnergy <= %s ) ' %
                                 str(J2invcm(energies[1])))
                elif energies[1] == "+Inf":
                    where.append(' ( upper.StateEnergy >= %s ) ' %
                                 str(J2invcm(energies[0])))
                else:
                    where.append(' ( upper.StateEnergy >= %s and \
                                 upper.StateEnergy <= %s ) ' %
                                 (str(J2invcm(energies[0])),
                                  str(J2invcm(energies[1]))))
            if len(energies) == 1:
                where.append(' ( upper.StateEnergy = %s )' %
                             str(J2invcm(energies[0])))
        if len(where) == 0:
            return None

        return 'select all where ' + 'AND'.join(where)

    def getMaxrec(self):
        if 'MAXREC' in self.request:
            result = int(self.request['MAXREC'][0])
            if result < 0:
                result = None
        else:
            result = None

        return result

    def getResponseFormat(self):
        if 'RESPONSEFORMAT' in self.request:
            result = str(self.request['RESPONSEFORMAT'][0])
            if result == "text/xml":
                return result

        return "application/x-votable+xml"

    def __str__(self):
        return '%s' % self.query


def doSlapQuery(query, query_type):
    """
    Execute SLAP request 
    """
    try:
        slapquery = SLAPQUERY(query, query_type)
    except Exception as err:
        emsg = 'Query processing in setupResults() failed: %s' % err
        log.debug(emsg)
        return tapServerError(status=400, errmsg=emsg)   

    try:
        print("max : " + str(slapquery.getMaxrec()))
        querysets = QUERYFUNC.setupResults(slapquery, slapquery.getMaxrec())
    except Exception as err:
        emsg = 'Query processing in setupResults() failed: %s' % err
        log.debug(emsg)
        return tapServerError(status=400, errmsg=emsg)

    response = HttpResponse('', status=204)
    print("SLAP")
    if query_type is SLAPQUERY.LINES_REQUEST:
        print("LINES")
        generator = SlapLines(MAXREC=slapquery.getMaxrec(), **querysets)
    elif query_type is SLAPQUERY.SPECIES_REQUEST:
        generator = SlapSpecies(**querysets)
    else:
        raise Error("Unknown query type")
    response = StreamingHttpResponse(generator,
                                     content_type=slapquery.getResponseFormat())
    response['Content-Disposition'] = 'attachment; filename=%s.xml' %\
                                      settings.NODENAME
    return response


def lines(query):
    """
    Returns a VOTALBE listing lines by wavelegnth and other optional criteria
    """
    return doSlapQuery(query, SLAPQUERY.LINES_REQUEST)


def species(query):
    """
    Returns a VOTABLE listing species in database
    """
    return doSlapQuery(query, SLAPQUERY.SPECIES_REQUEST)


def cleandict(indict):
    """
    throw out some keys
    """
    return {k: v for k, v in indict.items() if (v and '.' not in k)}


def capabilities(request):
    c = {"accessURL": getBaseURL(request, base="slap"),
         "restrictables": RESTRICTABLES}
    return render(request, 'slap/capabilities.xml',
                              c,
                              content_type='text/xml')


def availability(request):
    (status, message) = dbConnected()
    c = {'accessURL': getBaseURL(request, base="slap"),
         'ok': status,
         'message': message}
    return render(request, 'slap/availability.xml',
                              c,
                              content_type='text/xml')

def getBaseURL(request, base="tap"):
    return getattr(settings, 'DEPLOY_URL', None) or \
        'http://' + request.get_host() + request.path.split('/'+base ,1)[0] + '/'+ base +'/'
