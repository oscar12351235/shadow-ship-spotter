from __future__ import annotations

import numpy as np
import pandas as pd


def build_demo_frame() -> pd.DataFrame:
    values = np.linspace(0.0, 1.0, num=5)
    return pd.DataFrame({"x": values, "y": values**2})
