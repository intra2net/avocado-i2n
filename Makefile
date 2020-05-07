PYTHON=$(shell which python3 2>/dev/null)
COVERAGE=$(shell which coverage3 2>/dev/null)
PYTHON_DEVELOP_ARGS=$(shell if ($(PYTHON) setup.py develop --help 2>/dev/null | grep -q '\-\-user'); then echo "--user"; else echo ""; fi)
DESTDIR=/
PROJECT=avocado
AVOCADO_DIRNAME?=avocado

all:
	@echo
	@echo "List of available targets:"
	@echo "check:  Runs tree static check, unittests and functional tests"
	@echo "install:  Install on local system"
	@echo "clean:  Get rid of scratch and byte files"
	@echo "link:  Enables egg links and links needed resources"
	@echo "unlink:  Disables egg links and unlinks needed resources"
	@echo

check:
	$(COVERAGE) run --source=avocado_i2n -m unittest discover -v selftests
	$(COVERAGE) report -m

install:
	$(PYTHON) setup.py install --root $(DESTDIR)

clean:
	$(PYTHON) setup.py clean
	find . -name '*.pyc' -delete

develop:
	$(PYTHON) setup.py develop $(PYTHON_DEVELOP_ARGS)

link: develop

unlink:
	$(PYTHON) setup.py develop --uninstall $(PYTHON_DEVELOP_ARGS)
	# For compatibility reasons remove old symlinks
	for NAME in $$(ls -1 avocado_vt/conf.d); do\
		CONF="etc/avocado/conf.d/$$NAME";\
			[ -L ../$(AVOCADO_DIRNAME)/avocado/$$CONF ] && rm -f ../$(AVOCADO_DIRNAME)/avocado/$$CONF || true;\
			[ -L ../$(AVOCADO_DIRNAME)/$$CONF ] && rm -f ../$(AVOCADO_DIRNAME)/$$CONF || true;\
	done
