PYTHON=$(shell which python 2>/dev/null || which python3 2>/dev/null)
PYTHON_DEVELOP_ARGS=$(shell if ($(PYTHON) setup.py develop --help 2>/dev/null | grep -q '\-\-user'); then echo "--user"; else echo ""; fi)
DESTDIR=/
PROJECT=avocado
AVOCADO_DIRNAME?=avocado

all:
	@echo
	@echo "List of available targets:"
    @echo "install:  Install on local system"
	@echo "clean:  Get rid of scratch and byte files"
	@echo "link:  Enables egg links and links needed resources"
	@echo "unlink:  Disables egg links and unlinks needed resources"
	@echo


install:
	$(PYTHON) setup.py install --root $(DESTDIR)

clean:
	$(PYTHON) setup.py clean
	find . -name '*.pyc' -delete

link:
	for CONF in etc/avocado/conf.d/*; do\
		[ -d "../$(AVOCADO_DIRNAME)/avocado/etc/avocado/conf.d" ] && ln -srf $(CURDIR)/$$CONF ../$(AVOCADO_DIRNAME)/avocado/$$CONF || true;\
		[ -d "../$(AVOCADO_DIRNAME)/etc/avocado/conf.d" ] && ln -srf $(CURDIR)/$$CONF ../$(AVOCADO_DIRNAME)/$$CONF || true;\
	done
	$(PYTHON) setup.py develop  $(PYTHON_DEVELOP_ARGS)

unlink:
	$(PYTHON) setup.py develop --uninstall $(PYTHON_DEVELOP_ARGS)
	for CONF in etc/avocado/conf.d/*; do\
		[ -L ../$(AVOCADO_DIRNAME)/avocado/$$CONF ] && rm -f ../$(AVOCADO_DIRNAME)/avocado/$$CONF || true;\
		[ -L ../$(AVOCADO_DIRNAME)/$$CONF ] && rm -f ../$(AVOCADO_DIRNAME)/$$CONF || true;\
	done
