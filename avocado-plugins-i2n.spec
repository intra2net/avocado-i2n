# Basic RPM packaging for avocado-i2n with Python 3.

%global modulename avocado-i2n
%if ! 0%{?commit:1}
 # TODO: we will use a commit hash to match avocado-vt exactly since
 # it does not support release RPMs yet. Once our proposed release
 # extension is accepted upstream, we will also extend this spec file
 # to release mode (in addition to this snapshot mode) and only track
 # our own tags as is supposed to be.
 %define commit 8b85d88132209ff138200ec69ad01e48ffbf37fd
%endif
%global shortcommit %(c=%{commit}; echo ${c:0:8})

Summary: Avocado I2N Plugin
Name: python3-avocado-plugins-i2n
Version: 67.0
Release: 0%{?dist}
License: GPLv2
URL: https://github.com/intra2net/avocado-i2n/
Source0: https://github.com/intra2net/%{modulename}/archive/%{commit}/%{modulename}-%{version}-%{shortcommit}.tar.gz
BuildRequires: python3-devel, python3-setuptools
BuildArch: noarch
Requires: python3-avocado >= 51.0
Requires: python3-aexpect, python3-avocado-plugins-vt

%description
Avocado I2N is a plugin that extends the virt-tests functionality with
automated vm state setup, inheritance, and traversal using a Cartesian
graph structure.

%prep
%setup -q -n %{modulename}-%{commit}

%build
%{__python3} setup.py build

%install
%{__python3} setup.py install --root %{buildroot} --skip-build

%files
%defattr(-,root,root,-)
%dir /etc/avocado
%dir /etc/avocado/conf.d
%config(noreplace)/etc/avocado/conf.d/i2n.conf
%doc README.md LICENSE
%{python3_sitelib}/avocado_i2n*
%{python3_sitelib}/avocado_plugins_i2n*

%changelog
* Wed Feb  6 2019 Plamen Dimitrov <plamen.dimitrov@intra2net.com> - 67.0-0
- Updated calls from the state setup to the avocado LV utilities
- Dropped all LV utility patches needed to integrate with avocado

* Wed Feb  6 2019 Plamen Dimitrov <plamen.dimitrov@intra2net.com> - 66.0-0
- Release increment and changelog standardization

* Fri Dec 28 2018 Plamen Dimitrov <plamen.dimitrov@intra2net.com> - 65.0-1
- First release of the plugin with all migrated utilities
