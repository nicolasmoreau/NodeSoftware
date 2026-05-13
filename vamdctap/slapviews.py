# -*- coding: utf-8 -*-
from django.shortcuts import render
from django.http import HttpResponse, StreamingHttpResponse
from django.template import loader
import traceback
import logging
import os
import re
import math
import uuid
from base64 import b64encode
from django.conf import settings
from importlib import import_module
from requests.utils import CaseInsensitiveDict as CaselessDict
from .views import dbConnected
from vamdctap import unitconv
from .slapgenerators import *
from .sqlparse import SQL
from node.dictionaries import *
from .slapspeciesfilter import filterSpecies

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
# service specific slap parameters
SLAP_SERVICE_LINES_PARAMETERS = CaselessDict(DICTS.SLAP_LINES_PARAMETERS)

# complete list of standard SLAP2 /lines parameters
# an error must be returned if one of them is used but not implemented
STANDARD_SLAP_LINES_PARAMETERS = CaselessDict({
    "WAVELENGTH": None,
    "SPECIES": None,
    "SPECIES_MASS": None,
    "INCHIKEY": None,
    "ION_CHARGE": None,
    "LOWER_LEVEL_ENERGY": None,
    "UPPER_LEVEL_ENERGY": None,
    "TEMPERATURE": None,
    "EINSTEINA": None,
    "MAXREC": None,
    })

# complete list of standard SLAP2 /species parameters
STANDARD_SLAP_SPECIES_PARAMETERS = CaselessDict({
    "SPECIES_TYPE": None,
    "INCHIKEY": None,
    "INCHI": None,
    "NUMBER_OF_ATOMS": None,
    "SPECIES": None,
    "STOICHIOMETRIC_FORMULA": None,
})

# import helper modules that reside in the same directory
NODEID = CaselessDict(DICTS.RETURNABLES)['NodeID']


# This turns a 404 "not found" error into a TAP error-document
def slapNotFoundError(request, exception):
    text = 'Resource not found: %s'%request.path
    document = loader.get_template('slap/SLAP-error-document.xml').render({"error_message_text" : text})
    return HttpResponse(document, status=404, content_type='text/xml')

# This turns a 500 "internal server error" into a TAP error-document
def slapServerError(request=None, status=500, errmsg=''):
    text = 'Error in SLAP service: %s'%errmsg
    document = loader.get_template('slap/SLAP-error-document.xml').render({"error_message_text" : text})
    return HttpResponse(document, status=status, content_type='text/xml')


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
        self.HTTPmethod = request.method
        self.isvalid = True
        self.errormsg = ''
        # self.token = request.token
        try :
            if request_type == SLAPQUERY.LINES_REQUEST : 
                log.debug(request)
                self.checkSlapLinesParameters(request)
            elif request_type == SLAPQUERY.SPECIES_REQUEST : 
                self.checkSlapSpeciesParameters(request)
            else:
                raise Exception(f"Unknown request_type {request_type}")
        except Exception as e:
            print(e)
            traceback.print_exc()
            log.debug(self.errormsg)
            self.isvalid = False
            self.errormsg = e
            raise e

        try:
            # build a tap request from SLAP parameters
            tap_request = self.getTapRequestObject(CaselessDict(dict(request.GET or request.POST)), request_type)
            self.request = tap_request

        except Exception as e:
            print(e)
            traceback.print_exc()
            log.debug(self.errormsg)
            self.isvalid = False
            self.errormsg = 'Could not read argument dict: %s' % e
            raise e

        self.where = None
        if self.isvalid:
            self.validate()

        try : 
            self.fullurl = getBaseURL(request, base="slap") + \
                'sync?' + \
                request.META.get('QUERY_STRING')
        except Exception as e:
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
    
    def checkSlapLinesParameters(self, request):
        """ Return True is all the parameters are valid, 
            raise an exception if this is not the case

        """
        slap_params = {k.upper(): v for k, v in request.GET.dict().items()}
        log.debug('checkParameters')
        log.debug(slap_params)

        # WAVELENGTH is mandatory in query
        if "WAVELENGTH" not in slap_params :
            raise Exception("WAVELENGTH parameter is missing in query")
        for param in slap_params:
            # MAXREC is a DALI generic parameter handled at the framework level,
            # not in the node dictionary.
            if param == "MAXREC":
                continue
            # may be useful to have a distinction between the 2  cases
            # if param in STANDARD_SLAP_LINES_PARAMETERS and param not in SLAP_SERVICE_LINES_PARAMETERS:
            #    raise Exception("Parameter {} is not supported".format(param))
            if param not in SLAP_SERVICE_LINES_PARAMETERS:
                raise Exception("Parameter {} is not supported".format(param))
        return True
    
    def checkSlapSpeciesParameters(self, request):
        """Validate SLAP /species parameters.
        Raise an exception if an unknown parameter is received.
        Store validated parameters on self.species_params.

        Parameter names are case-insensitive (DALI spec). Multiple occurrences
        of the same parameter (case-insensitively) are aggregated into a list
        (OR semantics per SLAP2 spec section 3.1).
        """
        raw_params = request.GET or request.POST
        # Normalize keys to uppercase and aggregate multi-values
        normalized = {}
        for key in raw_params:
            upper_key = key.upper()
            if upper_key not in normalized:
                normalized[upper_key] = []
            normalized[upper_key].extend(raw_params.getlist(key))
        slap_params = CaselessDict(normalized)
        log.debug('checkSlapSpeciesParameters: %s', slap_params)
        for param in slap_params:
            if param not in STANDARD_SLAP_SPECIES_PARAMETERS:
                raise Exception("Parameter {} is not a valid SLAP /species parameter".format(param))
        self.species_params = slap_params
        return True

    def getSpeciesParams(self):
        """Return the species filter parameters extracted from the request."""
        return getattr(self, 'species_params', CaselessDict())
    
    def _buildInterval(self, values, vamdc_field, conversion_function=None):
        curr_values = list(map(float, values))
        if conversion_function is not None :
            curr_values = list(map(conversion_function, values))

        if len(values) == 2:
            if curr_values[0] == "-Inf":
                return (' ( %s <= %s ) ' % (vamdc_field, str(curr_values[1])))
            elif curr_values[1] == "+Inf" or curr_values[1] == "Inf":
                return (' ( %s >= %s ) ' % (vamdc_field, str(curr_values[0])))
            else:
                return (' ( %s >= %s and\
                                %s <= %s ) ' %
                            (vamdc_field, str(curr_values[0]), vamdc_field, str(curr_values[1])))
        else :
            if len(values) == 1:
                return (' ( %s = %s )' %  ( vamdc_field, str(curr_values[0])))


    def paramsToTap(self, request):
        """
        Converts SLAP parameters into a VAMDC-TAP request
        """
        where = []
        # slap parameter names are case insensitive
        slap_params = request
        for param, mapping in SLAP_SERVICE_LINES_PARAMETERS.items():
            restrictable = mapping.get('restrictable')
            convert_name = mapping.get('convert')
            is_interval = mapping.get('isInterval')
            result = []
            # several restrictables possible for a parameter
            if isinstance(restrictable, list):                
                for r in restrictable:
                    convert = getattr(unitconv, convert_name) if convert_name else lambda x: x
                    if r and ( param in slap_params ) and ( r in RESTRICTABLES ):                        
                        if is_interval :
                            for slap_param in slap_params[param] :
                                values = slap_param.split()
                                result.append(self._buildInterval(values, r, convert))
                        else :
                            for param_value in slap_params[param] :
                                result.append( f" ({r} = '{param_value}') ")
            if result:
                where.append("("+" OR ".join(result) + ")")
            # one restrictable for a parameter
            else:
                convert = getattr(unitconv, convert_name) if convert_name else lambda x: x
                if restrictable and ( param in slap_params ) and ( restrictable in RESTRICTABLES ):
                    if is_interval :
                        for slap_param in slap_params[param] :                  
                            values = slap_param.split()
                            result.append(self._buildInterval(values, restrictable, convert))
                    else :                     
                        for param_value in slap_params[param] :                  
                            result.append( f" ({restrictable} = '{param_value}') ")
                    where.append("("+" OR ".join(result) + ")")
            
        if len(where) == 0:
            return None

        log.debug("### query :" + str('select all where ' + ' AND '.join(where)) )
        return 'select all where ' + ' AND '.join(where)

    def getMaxrec(self):
        if 'MAXREC' in self.request:
            result = int(self.request['MAXREC'][0])
            if result < 0:
                result = None
        else:
            result = None

        return result

    def getResponseFormat(self):
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
        log.debug(traceback.format_exc())
        return slapServerError(status=400, errmsg=emsg)   

    log.debug("### slapquery :" + str(slapquery) )

    try:
        querysets = QUERYFUNC.setupResults(slapquery, slapquery.getMaxrec(), exact=True)
    except Exception as err:
        emsg = 'Query processing in setupResults() failed: %s' % err
        log.debug(emsg)
        log.debug(traceback.format_exc())
        return slapServerError(status=400, errmsg=emsg)
    
    log.debug("### querysets :" + str(querysets) )
    for q in querysets.values():
        log.debug(q)

    # Build the public-facing request URL using DEPLOY_URL (respects reverse proxy)
    endpoint = "lines" if query_type is SLAPQUERY.LINES_REQUEST else "species"
    qs = query.META.get('QUERY_STRING', '')
    slap_request_url = getBaseURL(query, base="slap") + endpoint + ('?' + qs if qs else '')

    response = HttpResponse('', status=204)
    if query_type is SLAPQUERY.LINES_REQUEST:
        generator = SlapLines(SlapQuery=slap_request_url, TapQuery=slapquery.request["QUERY"], MAXREC=slapquery.getMaxrec(), **querysets)
    elif query_type is SLAPQUERY.SPECIES_REQUEST:
        filtered_species = filterSpecies(slapquery.species_params, querysets['Molecules'])
        generator = SlapSpecies(SlapQuery=query.build_absolute_uri(), TapQuery=slapquery.request["QUERY"], Molecules=filtered_species)
    else:
        raise Error("Unknown query type")
    response = StreamingHttpResponse(generator,
                                     content_type=slapquery.getResponseFormat())
    #response['Content-Disposition'] = 'attachment; filename=%s.xml' %\
    #                                  settings.NODENAME
    response['Content-Disposition'] = 'attachment; filename=%s.xml' %\
                                      uuid.uuid4()

    return response


def lines(query):
    """
    Returns a VOTABLE listing lines by wavelegnth and other optional criteria
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
