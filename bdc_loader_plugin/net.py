"""Time limits of the plugin's HTTP requests, in seconds.

For requests a limit is the longest silence allowed on the connection, not the
length of the whole transfer; a pair is (connect, read).
"""

# Is the server there: the STAC root, the WTSS coverage list.
PING_S = 8
# One small answer: a collection description, a HEAD, a thumbnail.
METADATA_S = 15
# One page of STAC collections or items. A search over many tiles can keep the
# server busy for several seconds before the first byte.
STAC_PAGE_S = (10, 30)
# One WTSS time series request.
WTSS_SERIES_S = 30
# Silence inside a file transfer: an image band, a grid, the pip installer.
TRANSFER_S = 60
