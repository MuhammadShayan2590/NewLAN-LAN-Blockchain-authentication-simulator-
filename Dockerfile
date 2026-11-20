FROM freeradius/freeradius-server:latest
# Only the FreeRADIUS python module is needed: auth_bridge.py uses the standard library only
RUN apt-get update \
 && apt-get install -y --no-install-recommends freeradius-python3 \
 && rm -rf /var/lib/apt/lists/*
RUN rm -f /etc/freeradius/sites-enabled/default
COPY python3.conf /etc/freeradius/mods-enabled/python3
COPY default_site.conf /etc/freeradius/sites-enabled/default
COPY clients.conf /etc/freeradius/clients.conf
