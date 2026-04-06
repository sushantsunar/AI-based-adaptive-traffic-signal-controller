
# WAPS Algorithm (Weighted Adaptive Priority System)


def calculate_priority(density, waiting, emergency, importance,
                       w1=0.4, w2=0.3, w3=0.2, w4=0.1):
    """
    Calculates priority score for each direction.

    density   -> vehicle count from YOLO
    waiting   -> waiting cycles
    emergency -> 1 if emergency vehicle detected
    importance-> road weight (main road / side road)
    """

    # Weighted multi-factor score from methodology:
    # P_i = w1*V_i + w2*T_i + w3*E_i + w4*L_i
    priority = (
        w1 * density +
        w2 * waiting +
        w3 * emergency +
        w4 * importance
    )

    return round(priority, 2)


# Dynamic minimum green time

def dynamic_gmin(density, alpha=0.5, beta=8):
    """
    density -> average vehicle count
    alpha   -> density weight
    beta    -> base time
    """

    gmin = 10 + alpha * density + beta
    return int(max(10, min(gmin, 35)))  # bounded


# Final green time calculation

def calculate_green_time(Gmin, density, alpha=1.2):
    """
    Gmin   -> minimum green time
    density-> vehicles
    k      -> density multiplier
    """

    # Adaptive green allocation:
    # G_i = G_min + alpha * V_i
    green = Gmin + alpha * density

    # bounds
    return int(max(15, min(green, 60)))
