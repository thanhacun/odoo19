import math

# deprecated using roundPartial instead
def roundPartialDown(number_to_round, resolution):
    """
    Return a number rounded down by resolution step
    REF: https://stackoverflow.com/questions/8118679/python-rounding-by-quarter-intervals

    Example: roundPartialDown(1.7, 0.25) => 1.5
             roundPartialDown(1.24, 0.25) => 1.0

    """
    res = round(number_to_round / resolution) * resolution
    if res > number_to_round:
        res -= resolution
    return res

def roundPartial(number_to_round, resolution, round_down=True):
    """
    Return a number rounded down (or up) by resolution step
    REF: https://stackoverflow.com/questions/8118679/python-rounding-by-quarter-intervals

    Example: roundPartial(1.7, 0.25) => 1.5
             roundPartial(1.24, 0.25) => 1.0
             roundPartial(0.4, 0.5, False) => 0.5
             roundPartial(1.7, 0.5, False) => 1.5

    """
    # res = round(number_to_round / resolution) * resolution

    # using math.floor to make sure always round down
    res = math.floor(number_to_round / resolution) * resolution
    if not round_down:
        if res < number_to_round:
            res += resolution
    return res
