import re
from node.dictionaries import *

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



def filterSpecies(species_params, species):  
    """
        Return species, filtered by SLAP /species parameters if provided.

        Filtering is done directly on the Django ORM because VAMDC-TAP
        does not support parameterized 'select species' queries.

        @type  species_params: dict or None
        @param species_params: SLAP /species parameters (CaselessDict)
        @rtype:   util_models.Result
        @return:  Result object
    """
    for s in species_params:
        # SPECIES: pattern matching on chemical name
        param = species_params.get(s)
        if param is not None and s in SLAP_SPECIES_PARAMETERS:
            normalize = SLAP_SPECIES_PARAMETERS[s].get('normalize')
            if normalize is not None:
                param = [normalize(v) for v in param]
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

    return species
