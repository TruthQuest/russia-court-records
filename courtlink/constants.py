"""Article lists shared by the collection and analysis steps."""

# Census: articles used only against expression and protest (political by construction)
CENSUS_ARTICLES = ["207.3", "280.3", "280.4", "284.1", "354.1"]
LEVELS = ["district", "regional"]

# Search priority when a case carries several articles: the most specific political article first
PRIORITY = ["207.3", "280.3", "280.4", "284.1", "284.2", "330.1", "354.1", "280.1", "205.2", "280", "282",
            "282.1", "282.2", "282.3", "282.4", "275", "275.1", "276", "205.5", "205.1", "205.3", "205.4",
            "212.1", "148", "128.1", "329", "317", "319", "207.2"]
