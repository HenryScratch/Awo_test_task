DONOR_CONFIG = {
    'network_timeout': 60.0,
    'network_retries': 1,
    'banned_status_codes': [403],
    'freeze_status_codes': [429],
    'retry_after_header': 'retry-after',
    'retry_after_max_time': 60.0*60, # 1h
    'freeze_time_initial': 5.0,
    'freeze_time_max': 60.0,
    'freeze_time_factor': 2.0,
    'api_cooldown_param': [5.0, 30.0], # not more than 1 req per 5 sec for 30 sec in a row
    'api_cooldown_mode': 'window',
    'api_domain': 'mpstats.io',
    'api_token_header_name': 'X-Mpstats-TOKEN',
    'api_token_env_name': 'MPSTATS_API_TOKEN',
    'api_passthrough_headers': [
        'content-type',
        'content-encoding',
    ],
    'api_default_headers': {
        'user-agent': 'curl/7.81.0',
        'content-type': 'application/json',
    },
    'api_http_cache_enabled': True,
    'api_http_cache_capacity': 30000, # items
    'api_http_cache_item_maxsize': 15*1024**2, # 15Mb
    'api_http_cache_size_threshold': 5*1024**2, # 5Mb
    'api_http_cache_default_ttl': 60.0*60*24, # 24h
    'api_http_cache_short_ttl': 60.0*60, # 1h
    'api_group_requests_cache_ttl': 60.0*2,
    'api_group_requests_path_re': [
        r'^/api/wb/get/item/\d+/',
        r'^/api/wb/tools/comments',
        r'^/api/wb/tools/attribute-report',
        r'^/api/wb/tools/check-rates-batch',
        r'^/api/seo/keywords/expanding',
        r'^/api/seo/description-generator/',
    ],
    'api_bind_requests_cache_ttl': 60.0*60*4, # 4h
    #SKU /api/wb/get/item/[0-9]+ d1 d2
    #https://analitika-wb-ozon.pro/api/wb/get/item/90159753/balance_by_region?d1=2024-05-24&d2=2024-06-22&d=2024-06-22
    #https://analitika-wb-ozon.pro/api/wb/get/item/90159753/colors?d1=2024-05-24&d2=2024-06-22
    #https://analitika-wb-ozon.pro/api/wb/get/item/90159753/sales?d1=2024-05-24&d2=2024-06-22

    #Category /api/wb/get/(ds/)?category d1 d2 path
    #https://analitika-wb-ozon.pro/api/wb/get/category?d1=2024-05-24&d2=2024-06-22&path=%D0%94%D0%B5%D1%82%D1%8F%D0%BC
    #https://analitika-wb-ozon.pro/api/wb/get/category/subcategories?d1=2024-05-24&d2=2024-06-22&path=%D0%94%D0%B5%D1%82%D1%8F%D0%BC
    #https://analitika-wb-ozon.pro/api/wb/get/category/brands?d1=2024-05-24&d2=2024-06-22&path=%D0%94%D0%B5%D1%82%D1%8F%D0%BC

    #Выбор ниши /api/wb/get/(ds/)?subject d1 d2 path
    #https://analitika-wb-ozon.pro/api/wb/get/subject?d1=2024-05-24&d2=2024-06-22&path=4018
    #https://analitika-wb-ozon.pro/api/wb/get/subject?d1=2024-05-24&d2=2024-06-22&path=4018
    #https://analitika-wb-ozon.pro/api/wb/get/ds/subject/weekly?path=4018
    #https://analitika-wb-ozon.pro/api/wb/get/ds/subject/trend?path=4018&period=month12

    # Поиск по запросу
    # https://analitika-wb-ozon.pro/api/wb/get/search?d1=2024-05-25&d2=2024-06-23&path=%D0%B4%D0%B5%D1%82%D1%81%D0%BA%D0%B8%D0%B5+%D1%81%D0%BF%D0%BE%D1%80%D1%82%D0%B8%D0%B2%D0%BD%D1%8B%D0%B5+%D0%BA%D0%BE%D1%81%D1%82%D1%8E%D0%BC%D1%8B&recalculate_margin=0
    
    # Продавцы
    # https://analitika-wb-ozon.pro/api/wb/get/seller?d1=2024-05-25&d2=2024-06-23&path=%D0%98%D0%9F+%D0%9A%D0%BE%D0%BD%D0%BE%D0%B2%D0%B0%D0%BB%D0%BE%D0%B2+%D0%90+%D0%9E&supplierId=105850&recalculate_margin=0
    
    # Бренды
    # https://analitika-wb-ozon.pro/api/wb/get/brand?d1=2024-05-25&d2=2024-06-23&path=Xplace&recalculate_margin=0

    # Похожие товары
    # https://analitika-wb-ozon.pro/api/wb/get/identical?d1=2024-05-25&d2=2024-06-23&path=72124874
    
    # ^/api/(oz|wb)/get/(ds/)?\w+ - все разделы вб
    'api_bind_requests_path_re': [
        {"path": r'^/api/(oz|wb|ym)/get/item/\d+/', "params": ("d1","d2")},
        {"path": r'^/api/(oz|wb|ym)/get/(ds/)?\w+', "params": ("d1","d2","path")},
    ],
    'api_default_routing_rules': {
        'allow': [
            r'^/api/wb',
            r'^/api/oz',
            r'^/api/seo',
            r'^/api/ym',
            '*',
        ],
        'deny': [
        ],
    },
    'api_daily_limits_per_account': {
        #r'^/api/wb': 500,
        #r'^/api/oz': 500,
        #r'^/api/seo': 500,
        #r'^/api/ym': 500,
    },
}

API_CONFIG = {
    'auth_token': 'auth',
    'task_timeout': 90.0,
    'workers_timeout': 30.0,
    'daily_limits_per_user': {
        #r'^/api/wb': 500,
        #r'^/api/oz': 500,
        #r'^/api/seo': 500,
        #r'^/api/ym': 500,
    },
    'unlimited_users': [
        r'^cache',
        r'^admin'
    ],
}

REDIS_CONFIG = {
    'host': 'redis',
    'port': 6379,
}

LOGGING_CONFIG = {
    'app': {
        'default': {
            'fmt': '%(levelname)-9s [%(asctime)s]  [%(name)s] %(message)s',
            'datefmt': '%H:%M:%S',
        },
    },
    'uvicorn': {
        'default': {
            'fmt': '%(levelname)-9s [%(asctime)s]  %(message)s',
            'datefmt': '%H:%M:%S',
        },
        'access': {
            'fmt': '%(levelname)-9s [%(asctime)s]  %(client_addr)s - "%(request_line)s" %(status_code)s',
            'datefmt': '%H:%M:%S',
        },
    },
}
