# -*- coding: utf-8 -*-

def classFactory(iface):
    from .gmu_romblon_operations import GmuRomblonOperations
    return GmuRomblonOperations(iface)
