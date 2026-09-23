import numpy as np
from backend.domain.train import TrainClass

class DelayModel:
    """
    Fits and samples realistic arrival/departure delay distributions for Indian Railways train classes.
    """

    @staticmethod
    def sample_delay_min(train_class: TrainClass, time_of_day_min: int = 480, seed: int = None) -> float:
        if seed is not None:
            np.random.seed(seed)

        # Peak hour multiplier (07:00-11:00 & 17:00-21:00)
        tod = time_of_day_min % 1440
        is_peak = (420 <= tod <= 660) or (1020 <= tod <= 1260)
        peak_mult = 1.4 if is_peak else 1.0

        if train_class == TrainClass.SUBURBAN_LOCAL:
            # Gamma(shape=2.5, scale=1.0) -> mean 2.5 min
            raw = np.random.gamma(shape=2.5, scale=1.0)
        elif train_class == TrainClass.INTERCITY:
            # Gamma(shape=1.5, scale=8.0) -> mean 12.0 min
            raw = np.random.gamma(shape=1.5, scale=8.0)
        else:  # FREIGHT_MAIL
            # Gamma(shape=2.0, scale=17.5) -> mean 35.0 min
            raw = np.random.gamma(shape=2.0, scale=17.5)

        return float(np.round(raw * peak_mult, 1))
