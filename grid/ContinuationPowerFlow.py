import sys
from numpy import angle, conj, exp, array, asmatrix, asarray, diag, r_, linalg, Inf, dot, zeros, shape, where, pi
from scipy.sparse import issparse, csr_matrix as sparse, hstack, vstack
from scipy.sparse.linalg import spsolve
from warnings import warn

from .BusDefinitions import *
from .GenDefinitions import *
from .BranchDefinitions import *
# from .power_flow import *
from .NewtonRaphsonPowerFlow import *
# from numba import jit


# @jit(cache=True)
def dSbus_dV(Ybus, V):
    """
    Computes partial derivatives of power injection w.r.t. voltage.

    Returns two matrices containing partial derivatives of the complex bus
    power injections w.r.t voltage magnitude and voltage angle respectively
    (for all buses). If C{Ybus} is a sparse matrix, the return values will be
    also. The following explains the expressions used to form the matrices::

        S = diag(V) * conj(Ibus) = diag(conj(Ibus)) * V

    Partials of V & Ibus w.r.t. voltage magnitudes::
        dV/dVm = diag(V / abs(V))
        dI/dVm = Ybus * dV/dVm = Ybus * diag(V / abs(V))

    Partials of V & Ibus w.r.t. voltage angles::
        dV/dVa = j * diag(V)
        dI/dVa = Ybus * dV/dVa = Ybus * j * diag(V)

    Partials of S w.r.t. voltage magnitudes::
        dS/dVm = diag(V) * conj(dI/dVm) + diag(conj(Ibus)) * dV/dVm
               = diag(V) * conj(Ybus * diag(V / abs(V)))
                                        + conj(diag(Ibus)) * diag(V / abs(V))

    Partials of S w.r.t. voltage angles::
        dS/dVa = diag(V) * conj(dI/dVa) + diag(conj(Ibus)) * dV/dVa
               = diag(V) * conj(Ybus * j * diag(V))
                                        + conj(diag(Ibus)) * j * diag(V)
               = -j * diag(V) * conj(Ybus * diag(V))
                                        + conj(diag(Ibus)) * j * diag(V)
               = j * diag(V) * conj(diag(Ibus) - Ybus * diag(V))

    For more details on the derivations behind the derivative code used
    in PYPOWER information, see:

    [TN2]  R. D. Zimmerman, "AC Power Flows, Generalized OPF Costs and
    their Derivatives using Complex Matrix Notation", MATPOWER
    Technical Note 2, February 2010.
    U{http://www.pserc.cornell.edu/matpower/TN2-OPF-Derivatives.pdf}

    @author: Ray Zimmerman (PSERC Cornell)
    """
    ib = range(len(V))

    if issparse(Ybus):
        Ibus = Ybus * V

        diagV = sparse((V, (ib, ib)))
        diagIbus = sparse((Ibus, (ib, ib)))
        diagVnorm = sparse((V / abs(V), (ib, ib)))
    else:
        Ibus = Ybus * asmatrix(V).T

        diagV = asmatrix(diag(V))
        diagIbus = asmatrix(diag( asarray(Ibus).flatten() ))
        diagVnorm = asmatrix(diag(V / abs(V)))

    dS_dVm = diagV * conj(Ybus * diagVnorm) + conj(diagIbus) * diagVnorm
    dS_dVa = 1j * diagV * conj(diagIbus - Ybus * diagV)

    return dS_dVm, dS_dVa

# @jit(cache=True)
def jacobian(Ybus, V, pvpq, pq):
    """
    Calculates the system Jacobian matrix
    :param Ybus: Admittance matrix
    :param V: Voltage vector
    :param pvpq: array of the pq and pv indices
    :param pq: array of the pq indices
    :return: The system Jacobian Matrix
    """
    dS_dVm, dS_dVa = dSbus_dV(Ybus, V)  # compute the derivatives

    J11 = dS_dVa[array([pvpq]).T, pvpq].real
    J12 = dS_dVm[array([pvpq]).T, pq].real
    J21 = dS_dVa[array([pq]).T, pvpq].imag
    J22 = dS_dVm[array([pq]).T, pq].imag

    J = vstack([
            hstack([J11, J12]),
            hstack([J21, J22])
            ], format="csr")
    return J

# @jit(cache=True)
def cpf_p(parameterization, step, z, V, lam, Vprv, lamprv, pv, pq, pvpq):
    """
    #CPF_P Computes the value of the CPF parameterization function.
    #
    #   P = CPF_P(PARAMETERIZATION, STEP, Z, V, LAM, VPRV, LAMPRV, PV, PQ)
    #
    #   Computes the value of the parameterization function at the current
    #   solution point.
    #
    #   Inputs:
    #       PARAMETERIZATION : Value of cpf.parameterization option
    #       STEP : continuation step size
    #       Z : normalized tangent prediction vector from previous step
    #       V : complex bus voltage vector at current solution
    #       LAM : scalar lambda value at current solution
    #       VPRV : complex bus voltage vector at previous solution
    #       LAMPRV : scalar lambda value at previous solution
    #       PV : vector of indices of PV buses
    #       PQ : vector of indices of PQ buses
    #
    #   Outputs:
    #       P : value of the parameterization function at the current point
    #
    #   See also CPF_PREDICTOR, CPF_CORRECTOR.

    #   MATPOWER
    #   Copyright (c) 1996-2015 by Power System Engineering Research Center (PSERC)
    #   by Shrirang Abhyankar, Argonne National Laboratory
    #   and Ray Zimmerman, PSERC Cornell
    #
    #   $Id: cpf_p.m 2644 2015-03-11 19:34:22Z ray $
    #
    #   This file is part of MATPOWER.
    #   Covered by the 3-clause BSD License (see LICENSE file for details).
    #   See http://www.pserc.cornell.edu/matpower/ for more info.

    ## evaluate P(x0, lambda0)
    """
    if parameterization == 1:        # natural
        if lam >= lamprv:
            P = lam - lamprv - step
        else:
            P = lamprv - lam - step

    elif parameterization == 2:    # arc length
        Va = angle(V)
        Vm = abs(V)
        Vaprv = angle(Vprv)
        Vmprv = abs(Vprv)
        a = r_[Va[pvpq], Vm[pq], lam]
        b = r_[Vaprv[pvpq], Vmprv[pq], lamprv]
        P = sum((a - b)**2) - step**2

    elif parameterization == 3:    # pseudo arc length
        nb = len(V)
        Va = angle(V)
        Vm = abs(V)
        Vaprv = angle(Vprv)
        Vmprv = abs(Vprv)
        a = z[r_[pv, pq, nb+pq, 2*nb+1]]
        b = r_[Va[pvpq], Vm[pq], lam]
        c = r_[Vaprv[pvpq], Vmprv[pq], lamprv]
        P = dot(a, b - c) - step

    return P

# @jit(cache=True)
def cpf_p_jac(parameterization, z, V, lam, Vprv, lamprv, pv, pq, pvpq):
    """
    #CPF_P_JAC Computes partial derivatives of CPF parameterization function.
    #
    #   [DP_DV, DP_DLAM ] = CPF_P_JAC(PARAMETERIZATION, Z, V, LAM, ...
    #                                                   VPRV, LAMPRV, PV, PQ)
    #
    #   Computes the partial derivatives of the continuation power flow
    #   parameterization function w.r.t. bus voltages and the continuation
    #   parameter lambda.
    #
    #   Inputs:
    #       PARAMETERIZATION : Value of cpf.parameterization option.
    #       Z : normalized tangent prediction vector from previous step
    #       V : complex bus voltage vector at current solution
    #       LAM : scalar lambda value at current solution
    #       VPRV : complex bus voltage vector at previous solution
    #       LAMPRV : scalar lambda value at previous solution
    #       PV : vector of indices of PV buses
    #       PQ : vector of indices of PQ buses
    #
    #   Outputs:
    #       DP_DV : partial of parameterization function w.r.t. voltages
    #       DP_DLAM : partial of parameterization function w.r.t. lambda
    #
    #   See also CPF_PREDICTOR, CPF_CORRECTOR.

    #   MATPOWER
    #   Copyright (c) 1996-2015 by Power System Engineering Research Center (PSERC)
    #   by Shrirang Abhyankar, Argonne National Laboratory
    #   and Ray Zimmerman, PSERC Cornell
    #
    #   $Id: cpf_p_jac.m 2644 2015-03-11 19:34:22Z ray $
    #
    #   This file is part of MATPOWER.
    #   Covered by the 3-clause BSD License (see LICENSE file for details).
    #   See http://www.pserc.cornell.edu/matpower/ for more info.
    """
    if parameterization == 1:   # natural
        npv = len(pv)
        npq = len(pq)
        dP_dV = zeros(npv + 2 * npq)
        if lam >= lamprv:
            dP_dlam = 1.0
        else:
            dP_dlam = -1.0

    elif parameterization == 2:  # arc length
        Va = angle(V)
        Vm = abs(V)
        Vaprv = angle(Vprv)
        Vmprv = abs(Vprv)
        dP_dV = 2 * (r_[Va[pvpq], Vm[pq]] - r_[Vaprv[pvpq], Vmprv[pq]])
        if lam == lamprv:   # first step
            dP_dlam = 1.0   # avoid singular Jacobian that would result from [dP_dV, dP_dlam] = 0
        else:
            dP_dlam = 2 * (lam - lamprv)

    elif parameterization == 3:  # pseudo arc length
        nb = len(V)
        dP_dV = z[r_[pv, pq, nb + pq]]
        dP_dlam = z[2 * nb + 1][0]

    return dP_dV, dP_dlam

# @jit(cache=True)
def cpf_corrector(Ybus, Sbus, V0, pv, pq, lam0, Sxfr, Vprv, lamprv, z, step, parameterization, tol, max_it, verbose):
    """
    # CPF_CORRECTOR  Solves the corrector step of a continuation power flow using a
    #   full Newton method with selected parameterization scheme.
    #   [V, CONVERGED, I, LAM] = CPF_CORRECTOR(YBUS, SBUS, V0, REF, PV, PQ, ...
    #                 LAM0, SXFR, VPRV, LPRV, Z, STEP, PARAMETERIZATION, MPOPT)
    #   solves for bus voltages and lambda given the full system admittance
    #   matrix (for all buses), the complex bus power injection vector (for
    #   all buses), the initial vector of complex bus voltages, and column
    #   vectors with the lists of bus indices for the swing bus, PV buses, and
    #   PQ buses, respectively. The bus voltage vector contains the set point
    #   for generator (including ref bus) buses, and the reference angle of the
    #   swing bus, as well as an initial guess for remaining magnitudes and
    #   angles. MPOPT is a MATPOWER options struct which can be used to
    #   set the termination tolerance, maximum number of iterations, and
    #   output options (see MPOPTION for details). Uses default options if
    #   this parameter is not given. Returns the final complex voltages, a
    #   flag which indicates whether it converged or not, the number
    #   of iterations performed, and the final lambda.
    #
    #   The extra continuation inputs are LAM0 (initial predicted lambda),
    #   SXFR ([delP+j*delQ] transfer/loading vector for all buses), VPRV
    #   (final complex V corrector solution from previous continuation step),
    #   LAMPRV (final lambda corrector solution from previous continuation step),
    #   Z (normalized predictor for all buses), and STEP (continuation step size).
    #   The extra continuation output is LAM (final corrector lambda).
    #
    #   See also RUNCPF.
    
    #   MATPOWER
    #   Copyright (c) 1996-2015 by Power System Engineering Research Center (PSERC)
    #   by Ray Zimmerman, PSERC Cornell,
    #   Shrirang Abhyankar, Argonne National Laboratory,
    #   and Alexander Flueck, IIT
    #
    #   Modified by Alexander J. Flueck, Illinois Institute of Technology
    #   2001.02.22 - corrector.m (ver 1.0) based on newtonpf.m (MATPOWER 2.0)
    #
    #   Modified by Shrirang Abhyankar, Argonne National Laboratory
    #   (Updated to be compatible with MATPOWER version 4.1)
    #
    #   $Id: cpf_corrector.m 2644 2015-03-11 19:34:22Z ray $
    #
    #   This file is part of MATPOWER.
    #   Covered by the 3-clause BSD License (see LICENSE file for details).
    #   See http://www.pserc.cornell.edu/matpower/ for more info.
    """

    # initialize
    converged = 0
    i = 0
    V = V0
    Va = angle(V)
    Vm = abs(V)
    lam = lam0             # set lam to initial lam0
    
    # set up indexing for updating V
    npv = len(pv)
    npq = len(pq)
    pvpq = r_[pv, pq]
    nj = npv+npq*2
    nb = len(V)         # number of buses
    j1 = 1

    '''
    # MATLAB code
    j2 = npv           # j1:j2 - V angle of pv buses
    j3 = j2 + 1
    j4 = j2 + npq      # j3:j4 - V angle of pq buses
    j5 = j4 + 1
    j6 = j4 + npq      # j5:j6 - V mag of pq buses
    j7 = j6 + 1
    j8 = j6 + 1        # j7:j8 - lambda
    '''

    # j1:j2 - V angle of pv buses
    j1 = 0
    j2 = npv
    # j3:j4 - V angle of pq buses
    j3 = j2
    j4 = j2 + npq
    # j5:j6 - V mag of pq buses
    j5 = j4
    j6 = j4 + npq
    j7 = j6
    j8 = j6+1
    
    # evaluate F(x0, lam0), including Sxfr transfer/loading
    mis = V * conj(Ybus * V) - Sbus - lam * Sxfr
    F = r_[mis[pvpq].real,
           mis[pq].imag]
    
    # evaluate P(x0, lambda0)
    P = cpf_p(parameterization, step, z, V, lam, Vprv, lamprv, pv, pq, pvpq)
    
    # augment F(x,lambda) with P(x,lambda)
    F = r_[F, P]
    
    # check tolerance
    normF = linalg.norm(F, Inf)
    # if verbose > 1:
    #     sys.stdout.write('\n it    max P & Q mismatch (p.u.)')
    #     sys.stdout.write('\n----  ---------------------------')
    #     sys.stdout.write('\n#3d        #10.3e' (i, normF))

    if normF < tol:
        converged = True
        if verbose:
            print('\nConverged!\n')

    # do Newton iterations
    while not converged and i < max_it:
        # update iteration counter
        i += 1
        
        # evaluate Jacobian
        J = jacobian(Ybus, V, pvpq, pq)
    
        dF_dlam = -r_[Sxfr[pvpq].real, Sxfr[pq].imag]
        dP_dV, dP_dlam = cpf_p_jac(parameterization, z, V, lam, Vprv, lamprv, pv, pq, pvpq)
    
        # augment J with real/imag -Sxfr and z^T
        '''
        J = [   J   dF_dlam 
              dP_dV dP_dlam ]
        '''
        J = vstack([
            hstack([J, dF_dlam.reshape(nj, 1)]),
            hstack([dP_dV, dP_dlam])
            ], format="csr")
    
        # compute update step
        dx = -spsolve(J, F)
    
        # update voltage
        if npv:
            Va[pv] += dx[j1:j2]

        if npq:
            Va[pq] += dx[j3:j4]
            Vm[pq] += dx[j5:j6]

        V = Vm * exp(1j * Va)
        Vm = abs(V)            # update Vm and Va again in case
        Va = angle(V)          # we wrapped around with a negative Vm
    
        # update lambda
        lam += dx[j7:j8][0]
    
        # evalute F(x, lam)
        mis = V * conj(Ybus * V) - Sbus - lam*Sxfr
        F = r_[mis[pv].real,
               mis[pq].real,
               mis[pq].imag]
    
        # evaluate P(x, lambda)
        # parameterization, step, z, V, lam, Vprv, lamprv, pv, pq, pvpq
        P = cpf_p(parameterization, step, z, V, lam, Vprv, lamprv, pv, pq, pvpq)
    
        # augment F(x,lambda) with P(x,lambda)
        F = r_[F, P]
    
        # check for convergence
        normF = linalg.norm(F, Inf)
        
        if verbose > 1:
            print('\n#3d        #10.3e', i, normF)
        
        if normF < tol:
            converged = 1
            if verbose:
                print('\nNewton''s method corrector converged in ', i, ' iterations.\n')
        
    
    if verbose:
        if not converged:
            print('\nNewton method corrector did not converge in  ', i, ' iterations.\n')

    return V, converged, i, lam, normF

# @jit(cache=True)
def cpf_predictor(V, lam, Ybus, Sxfr, pv, pq, step, z, Vprv, lamprv, parameterization):
    """
    %CPF_PREDICTOR  Performs the predictor step for the continuation power flow
    %   [V0, LAM0, Z] = CPF_PREDICTOR(VPRV, LAMPRV, YBUS, SXFR, PV, PQ, STEP, Z)
    %
    %   Computes a prediction (approximation) to the next solution of the
    %   continuation power flow using a normalized tangent predictor.
    %
    %   Inputs:
    %       V : complex bus voltage vector at current solution
    %       LAM : scalar lambda value at current solution
    %       YBUS : complex bus admittance matrix
    %       SXFR : complex vector of scheduled transfers (difference between
    %              bus injections in base and target cases)
    %       PV : vector of indices of PV buses
    %       PQ : vector of indices of PQ buses
    %       STEP : continuation step length
    %       Z : normalized tangent prediction vector from previous step
    %       VPRV : complex bus voltage vector at previous solution
    %       LAMPRV : scalar lambda value at previous solution
    %       PARAMETERIZATION : Value of cpf.parameterization option.
    %
    %   Outputs:
    %       V0 : predicted complex bus voltage vector
    %       LAM0 : predicted lambda continuation parameter
    %       Z : the normalized tangent prediction vector
    
    %   MATPOWER
    %   Copyright (c) 1996-2015 by Power System Engineering Research Center (PSERC)
    %   by Shrirang Abhyankar, Argonne National Laboratory
    %   and Ray Zimmerman, PSERC Cornell
    %
    %   $Id: cpf_predictor.m 2644 2015-03-11 19:34:22Z ray $
    %
    %   This file is part of MATPOWER.
    %   Covered by the 3-clause BSD License (see LICENSE file for details).
    %   See http://www.pserc.cornell.edu/matpower/ for more info.
    """
    # sizes
    nb = len(V)
    npv = len(pv)
    npq = len(pq)
    pvpq = r_[pv, pq]
    nj = npv+npq*2
    # compute Jacobian for the power flow equations
    J = jacobian(Ybus, V, pvpq, pq)
    
    dF_dlam = -r_[Sxfr[pvpq].real, Sxfr[pq].imag]
    dP_dV, dP_dlam = cpf_p_jac(parameterization, z, V, lam, Vprv, lamprv, pv, pq, pvpq)
    
    # linear operator for computing the tangent predictor
    '''
        J = [   J   dF_dlam
              dP_dV dP_dlam ]
    '''
    J = vstack([
        hstack([J, dF_dlam.reshape(nj, 1)]),
        hstack([dP_dV, dP_dlam])
        ], format="csr")

    Vaprv = angle(V)
    Vmprv = abs(V)
    
    # compute normalized tangent predictor
    s = zeros(npv + 2 * npq + 1)
    s[npv + 2 * npq] = 1                    # increase in the direction of lambda
    z[r_[pvpq, nb+pq, 2*nb]] = spsolve(J, s)  # tangent vector
    z /= linalg.norm(z)                         # normalize tangent predictor  (dividing by the euclidean norm)
    
    Va0 = Vaprv
    Vm0 = Vmprv
    lam0 = lam
    
    # prediction for next step
    Va0[pvpq] = Vaprv[pvpq] + step * z[pvpq]
    Vm0[pq] = Vmprv[pq] + step * z[nb+pq]
    lam0 = lam + step * z[2*nb]
    V0 = Vm0 * exp(1j * Va0)
        
    return V0, lam0, z


# def runcpf(base, target, step, parameterization, adapt_step, step_min, step_max, error_tol=1e-3,
#            tol=1e-6, max_it=20, stop_at='NOSE', verbose=False):
#     """
#     Runs a full AC continuation power flow using a normalized tangent
#     predictor and selected parameterization scheme, returning a
#     RESULTS struct and SUCCESS flag. Step size can be fixed or adaptive.
#
#     Args:
#         basecasedata:
#         targetcasedata:
#         step: continuation step length
#         parameterization: parameterization
#         adapt_step:  use adaptive step size?
#         verbose: display intermediate information?
#
#     Returns:
#         RESULTS : results struct, with the following fields:
#                 (all fields from the input MATPOWER case, i.e. bus, branch,
#                 gen, etc., but with solved voltages, power flows, etc.)
#                 order - info used in external <-> internal data conversion
#                 et - elapsed time in seconds
#                 success - success flag, 1 = succeeded, 0 = failed
#                 cpf - CPF output struct whose content depends on any
#                     user callback functions. Default contains fields:
#                     V_p - (nb x nsteps+1) complex bus voltages from
#                             predictor steps
#                     lam_p - (nsteps+1) row vector of lambda values from
#                             predictor steps
#                     V_c - (nb x nsteps+1) complex bus voltages from
#                             corrector steps
#                     lam_c - (nsteps+1) row vector of lambda values from
#                             corrector steps
#                     max_lam - maximum value of lambda in lam_c
#                     iterations - number of continuation steps performed
#         SUCCESS : the success flag can additionally be returned as
#                   a second output argument
#
#          MATPOWER
#         Copyright (c) 1996-2015 by Power System Engineering Research Center (PSERC)
#         by Ray Zimmerman, PSERC Cornell,
#         Shrirang Abhyankar, Argonne National Laboratory,
#         and Alexander Flueck, IIT
#
#         $Id: runcpf.m 2644 2015-03-11 19:34:22Z ray $
#
#         This file is part of MATPOWER.
#         Covered by the 3-clause BSD License (see LICENSE file for details).
#         See http://www.pserc.cornell.edu/matpower/ for more info.
#
#     """
#
#     ########################################
#     # INITIALIZE BASE CASE
#     ########################################
#
#     # read base case data
#     bus_base = base['bus']
#     branch_base = base['branch']
#     gen_base = base['gen']
#     baseMVA_base = base['baseMVA']
#
#     nb = shape(bus_base)[0]
#     nl = shape(branch_base)[0]
#     ng = shape(gen_base)[0]
#
#     # get bus index lists of each type of bus
#     ref, pv, pq, _ = bustypes(bus_base, gen_base);
#     pvpq = r_[pv, pq]
#
#     # generator info
#     onb = where(gen_base[:, GEN_STATUS] > 0)[0]    # which generators are on?
#     gbus_base = gen_base[onb, GEN_BUS]                 # what buses are they at?
#
#     ########################################
#     # INITIALIZE TARGET CASE
#     ########################################
#     # read target case data
#     bus_target = target['bus']
#     branch_target = target['branch']
#     gen_target = target['gen']
#     baseMVA_target = target['baseMVA']
#
#     # get bus index lists of each type of bus
#     #[ref, pv, pq] = bustypes(bus_target, gen_target)  # Not needed since we have this from the base case
#
#     # generator info
#     ont = where(gen_target[:, GEN_STATUS] > 0)[0]    # which generators are on?
#     gbus_target = gen_target[ont, GEN_BUS]           # what buses are they at?
#
#
#     ########################################
#     # RUN POWER FLOWS
#     ########################################
#     # t0 = clock;
#
#     # initial state
#     V0  = bus_base[:, VM] * exp(1j * pi/180 * bus_base[:, VA])
#     vcb = ones(nb)           # create mask of voltage-controlled buses
#     vcb[pq] = 0                    # exclude PQ buses
#     k = where(vcb[gbus_base])[0]           # in-service gens at v-c buses
#     V0[gbus_base[k]] = gen_base[onb[k], VG] / abs(V0[gen_base[k, GEN_BUS]]) * V0[gen_base[k, GEN_BUS]]
#
#     # build admittance matrices
#     Ybus, Yf, Yt, _, _ = PowerFlow.makeYbus(None, baseMVA_base, bus_base, branch_base)
#
#     # compute base case complex bus power injections (generation - load)
#     Sbus_base = PowerFlow.makeSbus(None, baseMVA_base, bus_base, gen_base)
#     # compute target case complex bus power injections (generation - load)
#     Sbus_target = PowerFlow.makeSbus(None, baseMVA_target, bus_target, gen_target)
#
#     # scheduled transfer
#     Sxfr = Sbus_target - Sbus_base
#
#     # Run the base case power flow solution
#     lam = 0
#     # (Ybus, Sbus, V0, pv, pq, tol, max_it, verbose=False)
#     V, success, iterations = newtonpf(Ybus, Sbus_base, V0, pv, pq, tol, max_it)
#
#     lam_prev = lam   # lam at previous step
#     V_prev = V     # V at previous step
#     continuation = 1
#     cont_steps = 0
#
#     z = zeros(2 * nb + 1)
#     z[2 * nb] = 1.0
#
#     # result arrays
#     Voltage_series = list()
#     Lambda_series = list()
#
#     while continuation:
#         cont_steps += 1
#
#         # prediction for next step
#         V0, lam0, z = cpf_predictor(V, lam, Ybus, Sxfr, pv, pq, step, z, V_prev, lam_prev, parameterization)
#
#         # save previous voltage, lambda before updating
#         V_prev = V
#         lam_prev = lam
#
#         # correction
#         V, success, i, lam = cpf_corrector(Ybus, Sbus_base, V0, ref, pv, pq, lam0, Sxfr, V_prev, lam_prev, z, step, parameterization, tol, max_it, verbose)
#         if not success:
#             continuation = 0
#             print('step ', cont_steps, ' : lambda = ', lam, ', corrector did not converge in ', i, ' iterations\n')
#             break
#
#         # print('Step: ', cont_steps, ' Lambda prev: ', lam_prev, ' Lambda: ', lam)
#         # print(V)
#         Voltage_series.append(V)
#         Lambda_series.append(lam)
#
#         if verbose > 2:
#             print('step ', cont_steps, ' : lambda = ', lam)
#         elif verbose > 1:
#             print('step ', cont_steps, ': lambda = ', lam, ', ', i, ' corrector Newton steps\n')
#
#         if type(stop_at) is str:
#             if stop_at.upper() == 'FULL':
#                 if abs(lam) < 1e-8:  # traced the full continuation curve
#                     if verbose:
#                         print('\nTraced full continuation curve in ', cont_steps, ' continuation steps\n')
#                     continuation = 0
#
#                 elif (lam < lam_prev) and (lam - step < 0):   # next step will overshoot
#                     step = lam             # modify step-size
#                     parameterization = 1   # change to natural parameterization
#                     adapt_step = 0         # disable step-adaptivity
#
#             elif stop_at.upper() == 'NOSE':
#                 if lam < lam_prev:                        # reached the nose point
#                     if verbose:
#                         print('\nReached steady state loading limit in ', cont_steps, ' continuation steps\n')
#                     continuation = 0
#             else:
#                 raise Exception('Stop point ' + stop_at + ' not recognised.')
#
#         else:  # if it is not a string
#             if lam < lam_prev:                             # reached the nose point
#                 if verbose:
#                     print('\nReached steady state loading limit in ', cont_steps, ' continuation steps\n')
#                 continuation = 0
#
#             elif abs(stop_at - lam) < 1e-8:  # reached desired lambda
#                 if verbose:
#                     print('\nReached desired lambda ', stop_at, ' in ', cont_steps, ' continuation steps\n')
#                 continuation = 0
#
#             elif (lam + step) > stop_at:    # will reach desired lambda in next step
#                 step = stop_at - lam         # modify step-size
#                 parameterization = 1           # change to natural parameterization
#                 adapt_step = 0                 # disable step-adaptivity
#
#         if adapt_step and continuation:
#             # Adapt stepsize
#             cpf_error = linalg.norm(r_[angle(V[pq]), abs(V[pvpq]), lam] - r_[angle(V0[pq]), abs(V0[pvpq]), lam0], Inf)
#
#             if cpf_error < error_tol:
#                 # Increase stepsize
#                 step = step * error_tol / cpf_error
#                 if step > step_max:
#                     step = step_max
#
#             else:
#                 # decrese stepsize
#                 step = step * error_tol / cpf_error
#                 if step < step_min:
#                     step = step_min
#
#     # update bus and gen matrices to reflect the loading and generation
#     # at the noise point
#     # bus_target[:, PD] = bus_base[:, PD] + lam * (bus_target[:, PD] - bus_base[:, PD])
#     # bus_target[:, QD] = bus_base[:, QD] + lam * (bus_target[:, QD] - bus_base[:, QD])
#     # gen_target[:, PG] = gen_base[:, PG] + lam * (gen_target[:, PG] - gen_base[:, PG])
#
#     # update data matrices with solution
#     # bus_target, gen_target, branch_target = pfsoln(baseMVA_target, bus_target, gen_target, branch_target, Ybus, Yf, Yt, V, ref, pv, pq)
#
#     #-----  output results  -----
#     # convert back to original bus numbering & print results
#     # [mpctarget.bus, mpctarget.gen, mpctarget.branch] = deal(bust, gent, brancht);
#     # if success
#     #     n = cpf_results.iterations + 1;
#     #     cpf_results.V_p = i2e_data(mpctarget, cpf_results.V_p, NaN(nb,n), 'bus', 1);
#     #     cpf_results.V_c = i2e_data(mpctarget, cpf_results.V_c, NaN(nb,n), 'bus', 1);
#     # end
#     # results = int2ext(mpctarget);
#     # results.cpf = cpf_results;
#     #
#     # # zero out result fields of out-of-service gens & branches
#     # if ~isempty(results.order.gen.status.off)
#     #   results.gen(results.order.gen.status.off, [PG QG]) = 0;
#     # end
#     # if ~isempty(results.order.branch.status.off)
#     #   results.branch(results.order.branch.status.off, [PF QF PT QT]) = 0;
#     # end
#     #
#     # if fname
#     #     [fd, msg] = fopen(fname, 'at');
#     #     if fd == -1
#     #         error(msg);
#     #     else
#     #         if mpopt.out.all == 0
#     #             printpf(results, fd, mpoption(mpopt, 'out.all', -1));
#     #         else
#     #             printpf(results, fd, mpopt);
#     #         end
#     #         fclose(fd);
#     #     end
#     # end
#     # printpf(results, 1, mpopt);
#
#     # save solved case
#     # if solvedcase
#     #     savecase(solvedcase, results);
#     # end
#
#     # if nargout
#     #     res = results;
#     #     if nargout > 1
#     #         suc = success;
#     #     end
#     # % else  # don't define res, so it doesn't print anything
#     # end
#
#     return Voltage_series, Lambda_series

# @jit(cache=True)
def runcpf2(Ybus, Sbus_base, Sbus_target, V, pv, pq, step, approximation_order, adapt_step, step_min, step_max,
            error_tol=1e-3, tol=1e-6, max_it=20, stop_at='NOSE', verbose=False):
    """
    Runs a full AC continuation power flow using a normalized tangent
    predictor and selected approximation_order scheme.

    Args:
        Ybus: Admittance matrix
        Sbus_base: Power array of the base solvable case
        Sbus_target: Power array of the case to be solved
        V: Voltage array of the base solved case
        pv: Array of pv indices
        pq: Array of pq indices
        step: Adaptation step
        approximation_order: order of the approximation {1, 2, 3}
        adapt_step: use adaptive step size?
        step_min: minimum step size
        step_max: maximum step size
        error_tol: Error tolerance
        tol: Solutions tolerance
        max_it: Maximum iterations
        stop_at: Value of Lambda to stop at. It can be a number or {'NOSE', 'FULL'}
        verbose: Display additional intermediate information?

    Returns:
        Voltage_series: List of all the voltage solutions from the base to the target
        Lambda_series: Lambda values used in the continuation

    MATPOWER
        Copyright (c) 1996-2015 by Power System Engineering Research Center (PSERC)
        by Ray Zimmerman, PSERC Cornell,
        Shrirang Abhyankar, Argonne National Laboratory,
        and Alexander Flueck, IIT

        $Id: runcpf.m 2644 2015-03-11 19:34:22Z ray $

        This file is part of MATPOWER.
        Covered by the 3-clause BSD License (see LICENSE file for details).
        See http://www.pserc.cornell.edu/matpower/ for more info.
    """

    ########################################
    # INITIALIZATION
    ########################################

    # scheduled transfer
    Sxfr = Sbus_target - Sbus_base
    nb = len(Sbus_base)
    lam = 0
    lam_prev = lam   # lam at previous step
    V_prev = V       # V at previous step
    continuation = 1
    cont_steps = 0
    pvpq = r_[pv, pq]

    z = zeros(2 * nb + 1)
    z[2 * nb] = 1.0

    # result arrays
    Voltage_series = list()
    Lambda_series = list()

    # Voltage_series.append(V)
    # Lambda_series.append(lam)

    # Simulation
    while continuation:
        cont_steps += 1

        # prediction for next step
        V0, lam0, z = cpf_predictor(V, lam, Ybus, Sxfr, pv, pq, step, z, V_prev, lam_prev, approximation_order)

        # save previous voltage, lambda before updating
        V_prev = V
        lam_prev = lam

        # correction
        # Ybus, Sbus, V0, ref, pv, pq, lam0, Sxfr, Vprv, lamprv, z, step, parameterization, tol, max_it, verbose
        V, success, i, lam, normF = cpf_corrector(Ybus, Sbus_base, V0, pv, pq, lam0, Sxfr, V_prev, lam_prev, z,
                                                  step, approximation_order, tol, max_it, verbose)
        if not success:
            continuation = 0
            print('step ', cont_steps, ' : lambda = ', lam, ', corrector did not converge in ', i, ' iterations\n')
            break

        print('Step: ', cont_steps, ' Lambda prev: ', lam_prev, ' Lambda: ', lam)
        print(V)
        Voltage_series.append(V)
        Lambda_series.append(lam)

        if verbose > 2:
            print('step ', cont_steps, ' : lambda = ', lam)
        elif verbose > 1:
            print('step ', cont_steps, ': lambda = ', lam, ', ', i, ' corrector Newton steps\n')

        if type(stop_at) is str:
            if stop_at.upper() == 'FULL':
                if abs(lam) < 1e-8:  # traced the full continuation curve
                    if verbose:
                        print('\nTraced full continuation curve in ', cont_steps, ' continuation steps\n')
                    continuation = 0

                elif (lam < lam_prev) and (lam - step < 0):   # next step will overshoot
                    step = lam             # modify step-size
                    approximation_order = 1   # change to natural parameterization
                    adapt_step = 0         # disable step-adaptivity

            elif stop_at.upper() == 'NOSE':
                if lam < lam_prev:                        # reached the nose point
                    if verbose:
                        print('\nReached steady state loading limit in ', cont_steps, ' continuation steps\n')
                    continuation = 0
            else:
                raise Exception('Stop point ' + stop_at + ' not recognised.')

        else:  # if it is not a string
            if lam < lam_prev:                             # reached the nose point
                if verbose:
                    print('\nReached steady state loading limit in ', cont_steps, ' continuation steps\n')
                continuation = 0

            elif abs(stop_at - lam) < 1e-8:  # reached desired lambda
                if verbose:
                    print('\nReached desired lambda ', stop_at, ' in ', cont_steps, ' continuation steps\n')
                continuation = 0

            elif (lam + step) > stop_at:    # will reach desired lambda in next step
                step = stop_at - lam         # modify step-size
                approximation_order = 1           # change to natural parameterization
                adapt_step = 0                 # disable step-adaptivity

        if adapt_step and continuation:
            # Adapt step size
            cpf_error = linalg.norm(r_[angle(V[pq]), abs(V[pvpq]), lam] - r_[angle(V0[pq]), abs(V0[pvpq]), lam0], Inf)

            if cpf_error < error_tol:
                # Increase step size
                step = step * error_tol / cpf_error
                if step > step_max:
                    step = step_max

            else:
                # Decrease step size
                step = step * error_tol / cpf_error
                if step < step_min:
                    step = step_min

    return Voltage_series, Lambda_series, normF, success
