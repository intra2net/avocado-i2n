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

%if 0%{?rhel}
    %global with_python3 0
%else
    %global with_python3 1
%endif

# The Python dependencies are already tracked by the python2
# or python3 "Requires".  This filters out the python binaries
# from the RPM automatic requires/provides scanner.
%global __requires_exclude ^/usr/bin/python[23]$

Summary: Avocado I2N Plugin
Name: avocado-plugins-i2n
Version: 69.0
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

%files -n python3-%{name}
%defattr(-,root,root,-)
%dir /etc/avocado
%dir /etc/avocado/conf.d
%config(noreplace)/etc/avocado/conf.d/i2n.conf
%doc README.md LICENSE
%{python3_sitelib}/avocado_i2n*
%{python3_sitelib}/avocado_plugins_i2n*

%changelog
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
