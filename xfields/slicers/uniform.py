from pathlib import Path
import numpy as np
from ..general import _pkg_root

import xfields as xf
import xobjects as xo
import xtrack as xt

_configure_grid = xf.fieldmaps.interpolated._configure_grid

COORDS = ['x', 'px', 'y', 'py', 'zeta', 'delta']
SECOND_MOMENTS={}
for cc1 in COORDS:
    for cc2 in COORDS:
        if cc1 + '_' + cc2 in SECOND_MOMENTS or cc2 + '_' + cc1 in SECOND_MOMENTS:
            continue
        SECOND_MOMENTS[cc1 + '_' + cc2] = (cc1, cc2)

_xof = {
     'zeta_slice_centers': xo.Float64[:],
    'z_min_edge': xo.Float64,
    'num_slices': xo.Int64,
    'dzeta': xo.Float64,
    'num_bunches': xo.Int64,
    'filled_slots': xo.Int64[:],
    'bunch_numbers': xo.Int64[:],
    'bunch_spacing_zeta': xo.Float64,
    'num_particles': xo.Float64[:],
}
for cc in COORDS:
    _xof['sum_'+cc] = xo.Float64[:]
for ss in SECOND_MOMENTS:
    _xof['sum_'+ss] = xo.Float64[:]

short_second_mom_names={}
for ss in SECOND_MOMENTS:
    short_second_mom_names[ss.replace('_','')] = ss
# Gives {'xx': 'x_x', 'xpx': 'x_px', ...}

_rnm = {}

for kk in _xof.keys():
    _rnm[kk] = '_' + kk

class UniformBinSlicer(xt.BeamElement):

    _xofields = _xof
    _rename = _rnm

    iscollective = True

    _extra_c_sources = [
        xt.general._pkg_root.joinpath('headers/atomicadd.h'),
        _pkg_root.joinpath('slicers/slicers_src/uniform_bin_slicer.h')
    ]

    _per_particle_kernels = {
            '_slice_kernel_all': xo.Kernel(
                c_name='UniformBinSlicer_slice',
                args=[
                    xo.Arg(xo.Int64, name='use_bunch_index_array'),
                    xo.Arg(xo.Int64, name='use_edge_index_array'),
                    xo.Arg(xo.Int64, pointer=True, name='i_edge_particles'),
                    xo.Arg(xo.Int64, pointer=True, name='i_bunch_particles')
                ]),
            '_slice_kernel_x_only': xo.Kernel(
                c_name='UniformBinSlicer_slice_x_only',
                args=[
                    xo.Arg(xo.Int64, name='use_bunch_index_array'),
                    xo.Arg(xo.Int64, name='use_edge_index_array'),
                    xo.Arg(xo.Int64, pointer=True, name='i_edge_particles'),
                    xo.Arg(xo.Int64, pointer=True, name='i_bunch_particles')
                ]),
        }

    def __init__(self, zeta_range=None, num_slices=None, dzeta=None, zeta_slice_edges=None,
                 num_bunches=None,filling_scheme=None,bunch_numbers=None, bunch_spacing_zeta=None,
                 moments='all', **kwargs):

        self._slice_kernel = self._slice_kernel_all

        if '_xobject' in kwargs:
            self.xoinitialize(_xobject=kwargs['_xobject'])
            return

        num_edges = None
        if num_slices is not None:
            num_edges = num_slices + 1
        _zeta_slice_edges = _configure_grid('zeta', zeta_slice_edges, dzeta, zeta_range, num_edges)
        _zeta_slice_centers = _zeta_slice_edges[:-1] + (_zeta_slice_edges[1]-_zeta_slice_edges[0])/2

        if filling_scheme is None and bunch_numbers is None:
            if num_bunches is None:
                    num_bunches = 1
            filled_slots = np.arange(num_bunches,dtype=int)
            bunch_numbers = np.arange(num_bunches,dtype=int)
        else:
            assert num_bunches is None and filling_scheme is not None and bunch_numbers is not None
            filled_slots = filling_scheme.nonzero()[0]
            num_bunches = len(bunch_numbers)

        bunch_spacing_zeta = bunch_spacing_zeta or 0

        all_moments = COORDS + list(SECOND_MOMENTS.keys())
        if moments == 'all':
            selected_moments = all_moments
        else:
            assert isinstance (moments, (list, tuple))
            selected_moments = []
            for mm in moments:
                if mm in COORDS:
                    selected_moments.append(mm)
                elif mm in SECOND_MOMENTS:
                    selected_moments.append(mm)
                    for cc in SECOND_MOMENTS[mm]:
                        if cc not in SECOND_MOMENTS:
                            selected_moments.append(cc)
                elif mm in short_second_mom_names:
                    selected_moments.append(short_second_mom_names[mm])
                    for cc in SECOND_MOMENTS[short_second_mom_names[mm]]:
                        if cc not in SECOND_MOMENTS:
                            selected_moments.append(cc)
                else:
                    raise ValueError(f'Unknown moment {mm}')

        allocated_sizes = {}
        for mm in all_moments:
            if mm in selected_moments:
                allocated_sizes['sum_' + mm] = (num_bunches or 1) * len(_zeta_slice_centers)
            else:
                allocated_sizes['sum_' + mm] = 0

        self.xoinitialize(zeta_slice_centers=_zeta_slice_centers,
                          z_min_edge=_zeta_slice_edges[0], num_slices=len(_zeta_slice_centers),
                          dzeta=_zeta_slice_edges[1] - _zeta_slice_edges[0],
                          num_bunches=num_bunches,filled_slots=filled_slots, bunch_numbers=bunch_numbers,
                          bunch_spacing_zeta=bunch_spacing_zeta,
                          num_particles=(num_bunches or 1) * len(_zeta_slice_centers),
                          **allocated_sizes, **kwargs)


    def slice(self, particles, i_edge_particles=None, i_bunch_particles=None):

        self.clear()

        if i_bunch_particles is not None:
            use_bunch_index_array = 1
        else:
            use_bunch_index_array = 0
            i_bunch_particles = particles.particle_id[:1] # Dummy
        if i_edge_particles is not None:
            use_edge_index_array = 1
        else:
            use_edge_index_array = 0
            i_edge_particles = particles.particle_id[:1] # Dummy

        self._slice_kernel(particles=particles,
                           use_bunch_index_array=use_bunch_index_array,
                           use_edge_index_array=use_edge_index_array,
                           i_edge_particles=i_edge_particles,
                           i_bunch_particles=i_bunch_particles)

    def track(self, particles):
        self.slice(particles)

    def clear(self):
        for cc in COORDS:
            getattr(self, '_sum_' + cc)[:] = 0
        for ss in SECOND_MOMENTS:
            getattr(self, '_sum_' + ss)[:] = 0
        self.num_particles[:] = 0

    @property
    def zeta_centers(self):
        """
        Array with the grid points (bin centers).
        """
        if self.num_bunches <= 1:
            return self._zeta_slice_centers
        else:
            out = np.zeros((self.num_bunches, self.num_slices))
            for bunch_number in self.bunch_numbers:
                out[bunch_number, :] = (self._zeta_slice_centers - self._filled_slots[bunch_number] * self.bunch_spacing_zeta)
            return out

    @property
    def num_slices(self):
        """
        Number of bins
        """
        return self._num_slices

    @property
    def dzeta(self):
        """
        Bin size in meters.
        """
        return self._dzeta

    @property
    def num_bunches(self):
        """
        Number of bunches
        """
        return len(self._bunch_numbers)

    @property
    def filled_slots(self):
        """
        Filled slots
        """
        return self._filled_slots
        
    @property
    def bunch_numbers(self):
        """
        Number of bunches
        """
        return self._bunch_numbers

    @property
    def bunch_spacing_zeta(self):
        """
        Spacing between bunches in meters
        """
        return self._bunch_spacing_zeta

    @property
    def moments(self):
        """
        List of moments that are being recorded
        """
        out = []
        for cc in COORDS:
            if len(getattr(self._xobject, 'sum_' + cc)) > 0:
                out.append(cc)
        for ss in SECOND_MOMENTS:
            if len(getattr(self._xobject, 'sum_' + ss)) > 0:
                out.append(ss)

        return out

    @property
    def num_particles(self):
        """
        Number of particles per slice
        """
        return self._reshape_for_multibunch(self._num_particles)

    def sum(self, cc, cc2=None):
        """
        Sum of the quantity cc per slice
        """
        if cc in short_second_mom_names:
            cc = short_second_mom_names[cc]
        if cc2 is not None:
            cc = cc + '_' + cc2
        if len(getattr(self._xobject, 'sum_' + cc)) == 0:
            raise ValueError(f'Moment `{cc}` not recorded')
        return self._reshape_for_multibunch(getattr(self, '_sum_' + cc))

    def mean(self, cc, cc2=None):
        """
        Mean of the quantity cc per slice
        """
        out = 0 * self.num_particles
        mask_nonzero = self.num_particles > 0
        out[mask_nonzero] = (self.sum(cc, cc2)[mask_nonzero]
                             / self.num_particles[mask_nonzero])
        return out

    def cov(self, cc1, cc2=None):
        """
        Covariance between cc1 and cc2 per slice
        """
        if cc2 is None:
            if cc1 in short_second_mom_names:
                cc1 = short_second_mom_names[cc1]
            cc1, cc2 = cc1.split('_')
        return self.mean(cc1, cc2) - self.mean(cc1) * self.mean(cc2)

    def var(self, cc):
        """
        Variance of the quantity cc per slice
        """
        return self.cov(cc, cc)

    def std(self, cc):
        """
        Standard deviation of the quantity cc per slice
        """
        return np.sqrt(self.var(cc))

    def _reshape_for_multibunch(self, data):
        if self.num_bunches <= 0:
            return data
        else:
            return data.reshape(self.num_bunches, self.num_slices)

    def _to_npbuffer(self):
        assert isinstance(self._context, xo.ContextCpu)
        assert self._buffer.buffer.dtype == np.int8
        return self._buffer.buffer[self._offset:self._offset + self._xobject._size]

    @classmethod
    def _from_npbuffer(cls, buffer):

        assert isinstance(buffer, np.ndarray)
        assert buffer.dtype == np.int8
        xobuffer = xo.context_default.new_buffer(capacity=len(buffer))
        xobuffer.buffer = buffer
        offset = xobuffer.allocate(size=len(buffer))
        assert offset == 0
        return cls(_xobject=xf.UniformBinSlicer._XoStruct._from_buffer(xobuffer))

    def __iadd__(self, other):

        assert isinstance(other, UniformBinSlicer)
        assert self.num_slices == other.num_slices
        assert self.dzeta == other.dzeta
        assert self.filled_slots == other.filled_slots
        assert self.bunch_numbers == other.bunch_numbers

        for cc in COORDS:
            if len(getattr(self, '_sum_' + cc)) > 0:
                assert len(getattr(other, '_sum_' + cc)) > 0
                getattr(self, '_sum_' + cc)[:] += getattr(other, '_sum_' + cc)
        for ss in SECOND_MOMENTS:
            if len(getattr(self, '_sum_' + ss)) > 0:
                assert len(getattr(other, '_sum_' + ss)) > 0
                getattr(self, '_sum_' + ss)[:] += getattr(other, '_sum_' + ss)
        self.num_particles[:] += other.num_particles

        return self

    def __add__(self, other):
        if other == 0:
            return self.copy()
        out = self.copy()
        out += other
        return out

    def __radd__(self, other):
        if other == 0:
            return self.copy()
        return self.__add__(other)
