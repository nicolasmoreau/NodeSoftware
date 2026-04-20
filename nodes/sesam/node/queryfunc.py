# -*- coding: utf-8 -*-
#
# This module (which must have the name queryfunc.py) is responsible
# for converting incoming queries to a database query understood by
# this particular node's database schema.
#
# This module must contain a function setupResults, taking a sql object
# as its only argument.
#

# library imports
from itertools import chain
import re
from unittest import result
from vamdctap.sqlparse import sql2Q
from django.db.models import Q
from django.conf import settings
from node.dictionaries import *
from django.core.exceptions import ObjectDoesNotExist

import node.models as models
import node.util_models as util_models # utility classes
import logging

log = logging.getLogger("vamdc.node.queryfu")

if hasattr(settings,'LAST_MODIFIED'):
  LAST_MODIFIED = settings.LAST_MODIFIED
else: LAST_MODIFIED = None



def slapPatternToRegex(pattern):
    """Convert a SLAP shell wildcard pattern to an anchored regex string.

    SLAP wildcards: * (any sequence), ? (any char), [seq] (char class).
    All other characters are treated as literals.
    """
    result = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == '*':
            result.append('.*')
        elif c == '?':
            result.append('.')
        elif c == '[':
            # Copy bracket expression verbatim (it is valid regex syntax)
            j = i + 1
            if j < len(pattern) and pattern[j] in ('!', '^'):
                j += 1
            if j < len(pattern) and pattern[j] == ']':
                j += 1
            while j < len(pattern) and pattern[j] != ']':
                j += 1
            if j < len(pattern):
                result.append(pattern[i:j + 1])
                i = j
            else:
                result.append(re.escape(c))
        else:
            result.append(re.escape(c))
        i += 1
    return '^' + ''.join(result) + '$'


def applyPatternFilter(queryset, field, pattern):
    """Filter a queryset by a SLAP shell wildcard pattern on the given field."""
    regex = slapPatternToRegex(pattern)
    return queryset.filter(**{field + '__regex': regex})


def setupResults(sql, limit=None, exact=False):
    """
        Return results for request
        @type  sql: string
        @param sql: vss request
        @type  limit: int
        @param limit: maximum number of results
        @param limit : boolean
        @param limit : True to return the exact number defined by limit
        @rtype:   dict
        @return:  dictionnary containig data
    """
    result = None
    # return all species
    if str(sql).strip().lower() == 'select species':
        species_params = getattr(sql, 'species_params', None)
        result = setupSpecies(species_params)
    elif str(sql).strip().lower() == 'select sources':
        result = setupSources()
    # all other requests
    else:
        result = setupVssRequest(sql, limit, exact)

    if isinstance(result, util_models.Result) :
        return result.getResult()
    else:
        raise Exception('error while generating result')


def patternMatchingOr(src_queryset, parameter_values, field ):
    """
        Returns a queryset in which a pattern defined string has
        been searched

        @type src_queryset: queryset
        @param src_queryset: a queryset where search will be performed
        @type parameter_values: list
        @param parameter_values: a list of values to search
        @type field: string
        @param field: name of searched quantity 

        @return the filtered queryset
    """
    querysets = []
    if parameter_values is not None:
        for v in parameter_values:
            querysets.append(applyPatternFilter(src_queryset, field, v))
        src_queryset = querysets[0]
        for qs in querysets[1:]:
            src_queryset = src_queryset | qs
    return src_queryset

    
def buildInterval(src_queryset, field, values, convert):
    """
        Returns a queryset built from an interval defined in values.
        
        @type src_queryset: a queryset object
        @param src_queryset: the queryset that will be filtered with the interval
        @type field: string
        @param field: name of a field in the queryset
        @type values: list
        @param values: values defining the interval 
        @type convert: function
        @param convert: a function to convert results from the database unit to the standard unit

        @return: the filtered queryset object

    """
    if len(values) == 2:
        if values[0] == "-Inf":
            return src_queryset.filter(**{f'{field}__lte':convert(values[1])})
        elif values[1] == "+Inf" or values[1] == "Inf":
            return src_queryset.filter(**{f'{field}__gte':convert(values[0])})
        else:
            return src_queryset.filter(**{f'{field}__gte':convert(values[0]), f'{field}__lte':convert(values[1])})
    else :
        if len(values) == 1:
            return src_queryset.filter(**{f'{field}__exact':convert(values[0])})   
        
    return src_queryset


def setupSpecies(species_params=None):  
    """
        Return species, filtered by SLAP /species parameters if provided.

        Filtering is done directly on the Django ORM because VAMDC-TAP
        does not support parameterized 'select species' queries.

        @type  species_params: dict or None
        @param species_params: SLAP /species parameters (CaselessDict)
        @rtype:   util_models.Result
        @return:  Result object
    """

    def getORMColumns(parameter):
        """
            Return a list of model fields mapped against a SLAP parameter name
            in the SLAP_SPECIES_PARAMETERS dictionary

            @type parameter: string
            @param parameter: name of SLAP parameter
            @rtype: list
            @return: list of fields
        """
        result = []
        field = SLAP_SPECIES_PARAMETERS[parameter]['restrictable']
        if isinstance(field, list) is False:
            result.append(SPECIES_ORM_FIELDS[field])
        else :
            for f in field:                
                result.append(SPECIES_ORM_FIELDS[f])
        return result

    result = util_models.Result()
    species = models.Molecule.objects.all()
    for s in species_params:
        # SPECIES: pattern matching on chemical name
        param = species_params.get(s)
        if param is not None and s in SLAP_SPECIES_PARAMETERS:
            param_type = SLAP_SPECIES_PARAMETERS[s]['type']
            columns = getORMColumns(s)
            combined = None
            for column in columns :
                if param_type == "pattern" :
                    qs = patternMatchingOr(species, param, column)       
                elif param_type == "exact" :
                    qs = species.filter(**{f'{column}__in':param})
                elif param_type == "interval":
                    for p in param:
                        qs = buildInterval(species, column, p.split(), int)
                else :
                    raise Exception(f"Unknown parameter type {param_type}")

                combined = qs if combined is None else combined | qs
            if combined is not None :
                species = species.filter(pk__in=combined.values('pk'))

    result.addHeaderField('COUNT-SPECIES', len(species))
    result.addDataField('Molecules', species)
    return result

def setupSources():
	"""		
		Return all sources
		@rtype:   util_models.Result
		@return:  Result object		
	"""
	result = util_models.Result()
	sources = models.Source.objects.all()
	result.addHeaderField('COUNT-SOURCES',len(sources))
	result.addDataField('Sources',sources)	
	return result
	
def setupVssRequest(sql, limit=2000, exact=False):
    """		
        Execute a vss request
        @type  sql: string
        @param sql: vss request
        @rtype:   util_models.Result
        @return:  Result object		
    """
    result = util_models.Result()
    q = sql2Q(sql)
    #select transitions : combination of density/temperature
    transs = models.Radiativetransition.objects.filter(q)
    log.debug("SQL: %s", transs.query)
    ntranss=transs.count()
    methods = util_models.Methods()

    if limit is not None and limit < ntranss :
        transs, percentage = truncateTransitions(transs, q, limit, exact)
    else:
        percentage=None 
    #log.debug("number of transitions : "+str(ntranss))
    # Through the transition-matches, use our helper functions to extract 
    # all the relevant database data for our query. 
    if ntranss > 0 :	
        species, nspecies, nstates = getSpeciesWithStates(transs)      
        transitions = transs        
        sources =  getSources(transs)  
        nsources = len(sources)

        # Create the header with some useful info. The key names here are
        # standardized and shouldn't be changed.
        result.addHeaderField('TRUNCATED',percentage)
        result.addHeaderField('COUNT-SPECIES',nspecies)
        result.addHeaderField('COUNT-STATES',nstates)
        result.addHeaderField('COUNT-SOURCES',nsources)	
        result.addHeaderField('COUNT-RADIATIVE',len(transitions))	
        
        if LAST_MODIFIED is not None : 
          result.addHeaderField('LAST-MODIFIED',LAST_MODIFIED)
       
        result.addDataField('RadTrans',transitions)        
        result.addDataField('Molecules',species)
        result.addDataField('Methods',methods.getMethodsAsList())
        result.addDataField('Sources',sources)
        
    else : # only fill header
        result.addHeaderField('APPROX-SIZE', 0)    
        result.addHeaderField('TRUNCATED',percentage)
        result.addHeaderField('COUNT-STATES',0)
        result.addHeaderField('COUNT-RADIATIVE',0)
    return result	
	
def truncateTransitions(transitions, request, maxTransitionNumber, exact=False):
    """		
		limit the number of transitions
		@type  transitions: list
		@param transitions: a list of Transition
		@type  request: Q()
		@param request: sql query
		@type  maxTransitionNumber: int
		@param maxTransitionNumber: max number of transitions
		@rtype:   list
		@return:  truncated list of transitions		
    """
    percentage='%.1f' % (float(maxTransitionNumber) / transitions.count() * 100)
    transitions = transitions.order_by('wavelength')
    if exact :
        ids = list(transitions[:maxTransitionNumber].values_list('pk', flat=True))
        return models.Radiativetransition.objects.filter(pk__in=ids), percentage
    else:
        newmax = transitions[maxTransitionNumber].wavelength
        return models.Radiativetransition.objects.filter(request,Q(wavelength__lt=newmax)), percentage
    
def getSources(transs):
    sourceids = transs.values_list('source', flat=True).distinct()
    return models.Source.objects.filter(pk__in=sourceids)  
    
def getSpeciesWithStates(transs):
    """
        Use the Transition matches to obtain the related Species (only atoms in this example)
        and the states related to each transition.         
        We also return some statistics of the result 
        @type  transs: list
        @param transs: a list of Transition
        @rtype:   list
        @return:  a list of Species
        @rtype:   int
        @return:  number of species
        @rtype:   int
        @return:  number of states
        
    """
    # get ions according to selected transitions    
    moleculeids = transs.values_list('molecule', flat=True).distinct()
    species = models.Molecule.objects.filter(pk__in=moleculeids)   
        
    # get all states.    
    nstates = 0
    
    for specie in species:
        try :  
            # get all transitions in linked to this particular species 
            spec_transitions = transs.filter(molecule__pk = specie.pk)   
            # extract reference ids for the states from the transion, combining both
            # upper and lower unique states together
            up = spec_transitions.values_list('upperstate',flat=True)
            lo = spec_transitions.values_list('lowerstate',flat=True)
            sids = set(chain(up, lo))
            getStates(specie, sids)            
            
        except ObjectDoesNotExist as e:
          pass
            #log.debug(str(e)) 
    specie.States = list(set(specie.States))        
    nstates = len(specie.States)
    nspecies = len(species) # get some statistics 
    return species, nspecies, nstates  
    
def getStates(specie, sids):
    states = models.Molecularstate.objects.filter(pk__in = sids).distinct()
    datasets = states.values_list('dataset__pk',flat=True).distinct()
    #energy origin
    origin = models.Molecularstate.objects.filter(dataset__in = datasets, energy=0)[0]
    
    for state in states:        
        state.Case = models.Case.objects.get( molecularstate = state.id)
        state.SubCase = state.Case.getSubCase()
        state.origin = origin.pk
        
    origin.Case = models.Case.objects.get( molecularstate = origin.id)
    origin.SubCase = origin.Case.getSubCase()
    origin.origin = origin.pk       
        
    result_list = list(chain(states, [origin]))
        
    specie.States = result_list

    
