%global srcname avocado-i2n

# Conditional for release vs. snapshot builds. Set to 1 for release build.
%if ! 0%{?rel_build:1}
    %global rel_build 1
%endif

# Settings used for build from snapshots.
%if 0%{?rel_build}
    %global gittar          %{srcname}-%{version}.tar.gz
%else
    %if ! 0%{?commit:1}
        %global commit      8b85d88132209ff138200ec69ad01e48ffbf37fd
    %endif
    %if ! 0%{?commit_date:1}
        %global commit_date 20181212
    %endif
    %global shortcommit     %(c=%{commit};echo ${c:0:8})
    %global gitrel          .%{commit_date}git%{shortcommit}
    %global gittar          %{srcname}-%{shortcommit}.tar.gz
%endif

# Selftests are provided but may need to be skipped because many of
# the functional tests are time and resource sensitive and can
# cause race conditions and random build failures. They are
# enabled by default.
%global with_tests 1

Summary: Avocado I2N Plugin
Name: avocado-plugins-i2n
Version: 87.0
Release: 0%{?gitrel}%{?dist}
License: GPLv2
Group: Development/Tools
URL: https://github.com/intra2net/avocado-i2n/
%if 0%{?rel_build}
Source0: https://github.com/intra2net/%{srcname}/archive/%{version}.tar.gz#/%{gittar}
%else
Source0: https://github.com/intra2net/%{srcname}/archive/%{commit}.tar.gz#/%{gittar}
# old way of retrieving snapshot sources
#Source0: https://github.com/intra2net/%{srcname}/archive/%{commit}/%{srcname}-%{version}-%{shortcommit}.tar.gz
%endif
BuildRequires: python3-devel, python3-setuptools
BuildArch: noarch

%if %{with_tests}
BuildRequires: python3-coverage
%endif

%description
Avocado I2N is a plugin that extends the virt-tests functionality with
automated vm state setup, inheritance, and traversal using a Cartesian
graph structure.

%package -n python3-%{name}
Summary: %{summary}
Requires: python3-avocado >= 51.0
Requires: python3-aexpect, python3-avocado-plugins-vt
%{?python_provide:%python_provide python3-%{srcname}}
%description -n python3-%{name}
Avocado I2N is a plugin that extends the virt-tests functionality with
automated vm state setup, inheritance, and traversal using a Cartesian
graph structure.

%prep
%if 0%{?rel_build}
%setup -q -n %{srcname}-%{version}
%else
%setup -q -n %{srcname}-%{commit}
%endif

%build
%{__python3} setup.py build

%install
%{__python3} setup.py install --root %{buildroot} --skip-build
%{__mkdir} -p %{buildroot}%{_sysconfdir}/avocado/conf.d
%{__mv} %{buildroot}%{python3_sitelib}/avocado_i2n/conf.d/* %{buildroot}%{_sysconfdir}/avocado/conf.d

%if %{with_tests}
%check
make check
%endif

%files -n python3-%{name}
%defattr(-,root,root,-)
%dir %{_sysconfdir}/avocado
%dir %{_sysconfdir}/avocado/conf.d
%config(noreplace)%{_sysconfdir}/avocado/conf.d/i2n.conf
%doc README.md LICENSE
%{python3_sitelib}/avocado_i2n*
%{python3_sitelib}/avocado_framework_plugin_i2n*
%{_datadir}/avocado-plugins-i2n/tp_folder/*

%changelog
* Mon May 3 2021 Plamen Dimitrov <plamen.dimitrov@intra2net.com> - 87.0-0
- Extension of state setup to a python subpackage of configurable state backends
- New state pool backend to reuse off root states across processes

* Fri Sep 18 2020 Plamen Dimitrov <plamen.dimitrov@intra2net.com> - 82.0-0
- Some stability fixes due to improved unit test coverage
- Ability to rerun specific test nodes depending on status or unconditionally

* Tue Sep 1 2020 Plamen Dimitrov <plamen.dimitrov@intra2net.com> - 81.0-0
- Full compatibility with the unified global settings and setting types
- Full compatibility with the new multi-suite job API

* Tue Jun 9 2020 Plamen Dimitrov <plamen.dimitrov@intra2net.com> - 80.0-0
- Various fixes for the now stable API to conclude the 70s versions
- Various fixes of the currently less stable avocado upstream API

* Tue May 12 2020 Plamen Dimitrov <plamen.dimitrov@intra2net.com> - 79.0-0
- Deep state branch cloning revival, coverage, and tutorials (last old feature)
- Coverage improvements with elaborate dependency fixes and python 3.8 support

* Tue Apr 28 2020 Plamen Dimitrov <plamen.dimitrov@intra2net.com> - 78.0-0
- Full refactoring of the command line parser with unit test coverage
- API simplification of all test node and object parsing and running

* Wed Apr 15 2020 Plamen Dimitrov <plamen.dimitrov@intra2net.com> - 77.0-0
- Full refactoring of the cartgraph subpackage with formal permanent vm support
- OOP reimplementation of switchable state setup backends

* Wed Mar 4 2020 Plamen Dimitrov <plamen.dimitrov@intra2net.com> - 76.0-0
- Default sample test suite installation with develop mode accessibility
- Dropped requirements to use Intra2net avocado forks in order to run the plugin

* Fri Jan 24 2020 Plamen Dimitrov <plamen.dimitrov@intra2net.com> - 75.0-0
- Default and custom manual steps as tools or add-ons of the "manu" plugin
- Sample tool for GUI test development and virtual user backend stress testing

* Mon Dec 23 2019 Plamen Dimitrov <plamen.dimitrov@intra2net.com> - 74.0-0
- Support for all major linux variants by adding Debian derivatives
- Full revision of the sample test suite with regard to standalone readability

* Mon Dec 2 2019 Plamen Dimitrov <plamen.dimitrov@intra2net.com> - 73.0-0
- Improved defaults and configurable nic roles for the vmnet subpackage
- Fixes from LGTM automated reviews

* Sun Sep 29 2019 Plamen Dimitrov <plamen.dimitrov@intra2net.com> - 72.0-0
- Extention and interface unification of all vmnet test methods
- Full refactoring and documentation of the vmnet tunnel module

* Fri Sep 27 2019 Plamen Dimitrov <plamen.dimitrov@intra2net.com> - 71.0-0
- Compatibility fixes for vmnet's DNSMASQ backend

* Wed Jun 26 2019 Plamen Dimitrov <plamen.dimitrov@intra2net.com> - 70.0-0
- Fully migrated heterogeneous variantization and vm network
- Improved integration with Cartesian config join/suffix operators
- Refactoring into cartgraph and vmnet subpackages

* Sun Feb 24 2019 Plamen Dimitrov <plamen.dimitrov@intra2net.com> - 69.0-0
- Improved integration with human output and HTML plugins
- Refactoring into test structures, loaders, and runners

* Fri Feb 15 2019 Plamen Dimitrov <plamen.dimitrov@intra2net.com> - 68.0-0
- Sample test provider (test suite) for documentation and unit tests
- Setup for ReadTheDocs and Travis CI triggers

* Wed Feb  6 2019 Plamen Dimitrov <plamen.dimitrov@intra2net.com> - 67.0-0
- Updated calls from the state setup to the avocado LV utilities
- Dropped all LV utility patches needed to integrate with avocado

* Wed Feb  6 2019 Plamen Dimitrov <plamen.dimitrov@intra2net.com> - 66.0-0
- Release increment and changelog standardization

* Fri Dec 28 2018 Plamen Dimitrov <plamen.dimitrov@intra2net.com> - 65.0-1
- First release of the plugin with all migrated utilities
