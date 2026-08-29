AM_CPPFLAGS = -I$(top_srcdir) -I$(top_srcdir)/headers

check_PROGRAMS = iso_projection_test
TESTS = $(check_PROGRAMS)

iso_projection_test_SOURCES = \
	iso_projection_test.cc \
	$(top_srcdir)/gamerend/iso_projection.cc

iso_projection_test_LDADD = $(SYSLIBS)
