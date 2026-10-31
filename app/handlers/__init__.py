# -*- coding: utf-8 -*-
from .admin import router as admin_router
from .catalog import router as catalog_router
from .payment import router as payment_router
from .profile import router as profile_router
from .promo import router as promo_router
from .start import router as start_router
from .topup import router as topup_router

# Порядок как в оригинальном main.py
routers = [
    admin_router,
    start_router,
    catalog_router,
    profile_router,
    promo_router,
    topup_router,
    payment_router,
]
