from astropy.cosmology import Planck15 as cosmo
import numpy as np
import pymc3 as pm
import time
from scipy.special import gamma
import matplotlib.pyplot as plt
#plt.switch_backend('Agg')
from scipy.interpolate import interp1d
import os
from astropy.io import fits

Mpc = 3.0856776e+24 #cm
kpc = 3.0856776e+21 #cm
msun = 1.9891e33 #g
mh = 1.66053904e-24 #proton mass in g


def plot_multi_methods(profs, deps, labels=None, outfile=None):
    if len(profs) != len(deps):
        print("ERROR: different numbers of profiles and deprojection elements")
        return

    print("Showing %d density profiles" % len(deps))
    if labels is None:
        labels = [None] * len(deps)

    fig = plt.figure(figsize=(13, 10))
    ax_size = [0.14, 0.14,
               0.83, 0.83]
    ax = fig.add_axes(ax_size)
    ax.minorticks_on()
    ax.tick_params(length=20, width=1, which='major', direction='in', right=True, top=True)
    ax.tick_params(length=10, width=1, which='minor', direction='in', right=True, top=True)
    for item in (ax.get_xticklabels() + ax.get_yticklabels()):
        item.set_fontsize(18)
    plt.xlabel('Radius [kpc]', fontsize=40)
    plt.ylabel('$n_{H}$ [cm$^{-3}$]', fontsize=40)
    plt.xscale('log')
    plt.yscale('log')
    for i in range(len(deps)):
        dep = deps[i]
        prof = profs[i]

        kpcp = cosmo.kpc_proper_per_arcmin(dep.z).value

        rkpc = prof.bins * kpcp
        erkpc = prof.ebins * kpcp

        plt.errorbar(rkpc, dep.dens, xerr=erkpc, yerr=[dep.dens - dep.dens_lo, dep.dens_hi - dep.dens], fmt='.',
                     color='C%d' % i, elinewidth=2,
                     markersize=7, capsize=3, label=labels[i])
        plt.fill_between(rkpc, dep.dens_lo, dep.dens_hi, color='C%d' % i, alpha=0.3)
    plt.legend(loc=0,fontsize=22)
    if outfile is not None:
        plt.savefig(outfile)
    else:
        plt.show(block=False)

# Function to calculate a linear operator transforming parameter vector into predicted model counts

def calc_linear_operator(rad,sourcereg,pars,area,expo,psf):
    # Select values in the source region
    rfit=rad[sourcereg]
    npt=len(rfit)
    npars=len(pars[:,0])
    areamul=np.tile(area[0:npt],npars).reshape(npars,npt)
    expomul=np.tile(expo[0:npt],npars).reshape(npars,npt)
    spsf=psf[0:npt,0:npt]
    
    # Compute linear combination of basis functions in the source region
    beta=np.repeat(pars[:,0],npt).reshape(npars,npt)
    rc=np.repeat(pars[:,1],npt).reshape(npars,npt)
    base=1.+np.power(rfit/rc,2)
    expon=-3.*beta+0.5
    func_base=np.power(base,expon)
    
    # Predict number of counts per annulus and convolve with PSF
    Ktrue=func_base*areamul*expomul
    Kconv=np.dot(spsf,Ktrue.T)
    
    # Recast into full matrix and add column for background
    nptot=len(rad)
    Ktot=np.zeros((nptot,npars+1))
    Ktot[0:npt,0:npars]=Kconv
    Ktot[:,npars]=area*expo
    return Ktot

# Function to create the list of parameters for the basis functions
nsh=4. # number of basis functions to set

def list_params(rad,sourcereg,nrc=None,nbetas=6):
    rfit=rad[sourcereg]
    npfit=len(rfit)
    if nrc is None:
        nrc = int(npfit/nsh)
    allrc=np.logspace(np.log10(rfit[2]),np.log10(rfit[npfit-1]/2.),nrc)
    #allbetas=np.linspace(0.4,3.,6)
    allbetas = np.linspace(0.6, 3., nbetas)
    nrc=len(allrc)
    nbetas=len(allbetas)
    rc=allrc.repeat(nbetas)
    betas=np.tile(allbetas,nrc)
    ptot=np.empty((nrc*nbetas,2))
    ptot[:,0]=betas
    ptot[:,1]=rc
    return ptot

# Function to create a linear operator transforming parameters into surface brightness

def calc_sb_operator(rad,sourcereg,pars):
    # Select values in the source region
    rfit=rad[sourcereg]
    npt=len(rfit)
    npars=len(pars[:,0])
    
    # Compute linear combination of basis functions in the source region
    beta=np.repeat(pars[:,0],npt).reshape(npars,npt)
    rc=np.repeat(pars[:,1],npt).reshape(npars,npt)
    base=1.+np.power(rfit/rc,2)
    expon=-3.*beta+0.5
    func_base=np.power(base,expon)
    
    # Recast into full matrix and add column for background
    nptot=len(rad)
    Ktot=np.zeros((nptot,npars+1))
    Ktot[0:npt,0:npars]=func_base.T
    Ktot[:,npars]=0.0
    return Ktot


def calc_sb_operator_psf(rad, sourcereg, pars, area, expo, psf):
    # Select values in the source region
    rfit = rad[sourcereg]
    npt = len(rfit)
    npars = len(pars[:, 0])

    areamul = np.tile(area[0:npt], npars).reshape(npars, npt)
    expomul = np.tile(expo[0:npt], npars).reshape(npars, npt)
    spsf = psf[0:npt, 0:npt]

    # Compute linear combination of basis functions in the source region
    beta = np.repeat(pars[:, 0], npt).reshape(npars, npt)
    rc = np.repeat(pars[:, 1], npt).reshape(npars, npt)
    base = 1. + np.power(rfit / rc, 2)
    expon = -3. * beta + 0.5
    func_base = np.power(base, expon)

    Ktrue = func_base * areamul * expomul
    Kconv = np.dot(spsf, Ktrue.T)

    # Recast into full matrix and add column for background
    nptot = len(rad)
    Ktot = np.zeros((nptot, npars + 1))
    Ktot[0:npt, 0:npars] = Kconv
    Ktot[:, npars] = area * expo
    return Ktot


def calc_int_operator(a, b, pars):
    # Select values in the source region
    npars = len(pars[:, 0])
    rads = np.array([a, b])
    npt = 2

    # Compute linear combination of basis functions in the source region
    beta = np.repeat(pars[:, 0], npt).reshape(npars, npt)
    rc = np.repeat(pars[:, 1], npt).reshape(npars, npt)
    base = 1. + np.power(rads / rc, 2)
    expon = -3. * beta + 1.5
    func_base = 2. * np.pi * np.power(base, expon) / (3 - 6 * beta) * rc**2

    # Recast into full matrix and add column for background
    Kint = np.zeros((npt, npars + 1))
    Kint[0:npt, 0:npars] = func_base.T
    Kint[:, npars] = 0.0
    return Kint


def list_params_density(rad,sourcereg,z,nrc=None,nbetas=6):
    rfit=rad[sourcereg]
    npfit=len(rfit)
    kpcp=cosmo.kpc_proper_per_arcmin(z).value
    if nrc is None:
        nrc = int(npfit/nsh)
    allrc=np.logspace(np.log10(rfit[2]),np.log10(rfit[npfit-1]/2.),nrc)*kpcp
    #allbetas=np.linspace(0.5,3.,6)
    allbetas = np.linspace(0.6, 3., nbetas)
    nrc=len(allrc)
    nbetas=len(allbetas)
    rc=allrc.repeat(nbetas)
    betas=np.tile(allbetas,nrc)
    ptot=np.empty((nrc*nbetas,2))
    ptot[:,0]=betas
    ptot[:,1]=rc
    return ptot

# Linear operator to transform parameters into density

def calc_density_operator(rad,sourcereg,pars,z):
    # Select values in the source region
    kpcp=cosmo.kpc_proper_per_arcmin(z).value
    rfit=rad*kpcp
    npt=len(rfit)
    npars=len(pars[:,0])
    
    # Compute linear combination of basis functions in the source region
    beta=np.repeat(pars[:,0],npt).reshape(npars,npt)
    rc=np.repeat(pars[:,1],npt).reshape(npars,npt)
    base=1.+np.power(rfit/rc,2)
    expon=-3.*beta
    func_base=np.power(base,expon)
    cfact=gamma(3*beta)/gamma(3*beta-0.5)/np.sqrt(np.pi)/rc
    fng=func_base*cfact
    
    # Recast into full matrix and add column for background
    nptot=len(rfit)
    Ktot=np.zeros((nptot,npars+1))
    Ktot[0:npt,0:npars]=fng.T
    Ktot[:,npars]=0.0
    return Ktot

def Deproject_Multiscale_Stan(deproj,bkglim=None,nmcmc=1000,back=None,samplefile=None,nrc=None,nbetas=6,depth=10):
    prof = deproj.profile
    sb = prof.profile
    rad = prof.bins
    erad = prof.ebins
    counts = prof.counts
    area = prof.area
    exposure = prof.effexp
    bkgcounts = prof.bkgcounts

    # Define maximum radius for source deprojection, assuming we have only background for r>bkglim
    if bkglim is None:
        bkglim=np.max(rad+erad)
        deproj.bkglim = bkglim
        if back is None:
            back = sb[len(sb) - 1]
    else:
        deproj.bkglim = bkglim
        backreg = np.where(rad>bkglim)
        if back is None:
            back = np.mean(sb[backreg])

    # Set source region
    sourcereg = np.where(rad < bkglim)
    nptfit = len(sb[sourcereg])

    # Set vector with list of parameters
    pars = list_params(rad, sourcereg, nrc, nbetas)
    npt = len(pars)

    if prof.psfmat is not None:
        psfmat = np.transpose(prof.psfmat)
    else:
        psfmat = np.eye(prof.nbin)

    # Compute linear combination kernel
    K = calc_linear_operator(rad, sourcereg, pars, area, exposure, psfmat)
    if np.isnan(sb[0]) or sb[0] <= 0:
        testval = -10.
    else:
        testval = np.log(sb[0] / npt)
    if np.isnan(back) or back == 0:
        testbkg = -10.
    else:
        testbkg = np.log(back)

    norm0=np.append(np.repeat(testval,npt),testbkg)

    import pystan
    import stan_utility as su

    stan_dir = os.path.expanduser('~/.stan_cache')
    if not os.path.exists(stan_dir):
        os.makedirs(stan_dir)

    code = '''
    data {
    int<lower=0> N;
    int<lower=0> M;
    int cts_tot[N];
    vector[N] cts_back;
    matrix[N,M] K;
    vector[M] norm0;
    }
    parameters {
    vector[M] log_norm;
    }
    transformed parameters{
    vector[M] norm = exp(log_norm);
    }
    model {
    log_norm ~ normal(norm0,10);
    cts_tot ~ poisson(K * norm + cts_back);
    }'''


    f = open('mybeta_GP.stan', 'w')
    print(code, file=f)
    f.close()
    sm = su.compile_model('mybeta_GP.stan', model_name='model_GP')

    datas = dict(K=K, cts_tot=counts.astype(int), cts_back=bkgcounts, N=K.shape[0], M=K.shape[1],
                 norm0=norm0)
    tinit = time.time()
    print('Running MCMC...')
    fit = sm.sampling(data=datas, chains=1, iter=nmcmc, thin=1, n_jobs=1, control={'max_treedepth': depth})
    print('Done.')
    tend = time.time()
    print(' Total computing time is: ', (tend - tinit) / 60., ' minutes')
    chain = fit.extract()
    samples = chain['log_norm']

    # Get chains and save them to file

    if samplefile is not  None:
        np.savetxt(samplefile, samples)

    # Compute output deconvolved brightness profile
    Ksb = calc_sb_operator(rad, sourcereg, pars)
    allsb = np.dot(Ksb, np.exp(samples.T))
    bfit = np.median(np.exp(samples[:, npt]))
    pmc = np.median(allsb, axis=1)
    pmcl = np.percentile(allsb, 50. - 68.3 / 2., axis=1)
    pmch = np.percentile(allsb, 50. + 68.3 / 2., axis=1)

    deproj.samples = samples
    deproj.sb = pmc
    deproj.sb_lo = pmcl
    deproj.sb_hi = pmch
    deproj.bkg = bfit
    
    
    
def Deproject_Multiscale_PyMC3(deproj,bkglim=None,nmcmc=1000,back=None,samplefile=None,nrc=None,nbetas=6):
    prof = deproj.profile
    sb = prof.profile
    rad = prof.bins
    erad = prof.ebins
    counts = prof.counts
    area = prof.area
    exposure = prof.effexp
    bkgcounts = prof.bkgcounts

    # Define maximum radius for source deprojection, assuming we have only background for r>bkglim
    if bkglim is None:
        bkglim=np.max(rad+erad)
        deproj.bkglim = bkglim
        if back is None:
            back = sb[len(sb) - 1]
    else:
        deproj.bkglim = bkglim
        backreg = np.where(rad>bkglim)
        if back is None:
            back = np.mean(sb[backreg])

    # Set source region
    sourcereg = np.where(rad < bkglim)
    nptfit = len(sb[sourcereg])

    # Set vector with list of parameters
    pars = list_params(rad, sourcereg, nrc, nbetas)
    npt = len(pars)

    if prof.psfmat is not None:
        psfmat = np.transpose(prof.psfmat)
    else:
        psfmat = np.eye(prof.nbin)

    # Compute linear combination kernel
    K = calc_linear_operator(rad, sourcereg, pars, area, exposure, psfmat)
    basic_model = pm.Model()
    if np.isnan(sb[0]) or sb[0] <= 0:
        testval = -10.
    else:
        testval = np.log(sb[0] / npt)
    if np.isnan(back) or back == 0:
        testbkg = -10.
    else:
        testbkg = np.log(back)

    with basic_model:
        # Priors for unknown model parameters
        coefs = pm.Normal('coefs', mu=testval, sd=20, shape=npt)
        bkgd = pm.Normal('bkg', mu=testbkg, sd=0.05, shape=1)
        ctot = pm.math.concatenate((coefs, bkgd), axis=0)

        # Expected value of outcome
        al = pm.math.exp(ctot)
        pred = pm.math.dot(K, al) + bkgcounts

        # Likelihood (sampling distribution) of observations
        Y_obs = pm.Poisson('counts', mu=pred, observed=counts)

    tinit = time.time()
    print('Running MCMC...')
    with basic_model:
        #tm = pm.find_MAP()
        #trace = pm.sample(nmcmc, start=tm)
        trace = pm.sample(nmcmc)
    print('Done.')
    tend = time.time()
    print(' Total computing time is: ', (tend - tinit) / 60., ' minutes')

    # Get chains and save them to file
    sampc = trace.get_values('coefs')
    sampb = trace.get_values('bkg')
    samples = np.append(sampc, sampb, axis=1)
    if samplefile is not  None:
        np.savetxt(samplefile, samples)

    # Compute output deconvolved brightness profile
    Ksb = calc_sb_operator(rad, sourcereg, pars)
    allsb = np.dot(Ksb, np.exp(samples.T))
    bfit = np.median(np.exp(samples[:, npt]))
    pmc = np.median(allsb, axis=1)
    pmcl = np.percentile(allsb, 50. - 68.3 / 2., axis=1)
    pmch = np.percentile(allsb, 50. + 68.3 / 2., axis=1)

    deproj.samples = samples
    deproj.sb = pmc
    deproj.sb_lo = pmcl
    deproj.sb_hi = pmch
    deproj.bkg = bfit



class MyDeprojVol:
    '''
    Mydeproj
    '''
    def __init__(self, radin, radot):
        '''

        :param radin:

        :param radot:
        '''
        self.radin=radin
        self.radot=radot
        self.help=''

    def deproj_vol(self):
        ###############volume=deproj_vol(radin,radot)
        ri=np.copy(self.radin)
        ro=np.copy(self.radot)

        diftot=0
        for i in range(1,len(ri)):
            dif=abs(ri[i]-ro[i-1])/ro[i-1]*100.
            diftot=diftot+dif
            ro[i-1]=ri[i]

        if abs(diftot) > 0.1:
            print(' DEPROJ_VOL: WARNING - abs(ri(i)-ro(i-1)) differs by',diftot,' percent')
            print(' DEPROJ_VOL: Fixing up radii ... ')
            for i in range(1,len(ri)-1):
                dif=abs(ri[i]-ro[i-1])/ro[i-1]*100.
                diftot=diftot+dif
        nbin=len(ro)
        volconst=4./3.*np.pi
        volmat=np.zeros((nbin, nbin))

        for iring in list(reversed(range(0,nbin))):
            volmat[iring,iring]=volconst * ro[iring]**3 * (1.-(ri[iring]/ro[iring])**2.)**1.5
            for ishell in list(reversed(range(iring+1,nbin))):
                f1=(1.-(ri[iring]/ro[ishell])**2.)**1.5 - (1.-(ro[iring]/ro[ishell])**2.)**1.5
                f2=(1.-(ri[iring]/ri[ishell])**2.)**1.5 - (1.-(ro[iring]/ri[ishell])**2.)**1.5
                volmat[ishell,iring]=volconst * (f1*ro[ishell]**3 - f2*ri[ishell]**3)

                if volmat[ishell,iring] < 0.0:
                    exit()

        volume2=np.copy(volmat)
        return volume2

def medsmooth(prof):
    width=5
    nbin=len(prof)
    xx=np.empty((nbin,width))
    xx[:,0]=np.roll(prof,2)
    xx[:,1]=np.roll(prof,1)
    xx[:,2]=prof
    xx[:,3]=np.roll(prof,-1)
    xx[:,4]=np.roll(prof,-2)
    smoothed=np.median(xx,axis=1)
    smoothed[1]=np.median(xx[1,1:width])
    smoothed[nbin-2]=np.median(xx[nbin-2,0:width-1])
    Y0=3.*prof[0]-2.*prof[1]
    xx=np.array([Y0,prof[0],prof[1]])
    smoothed[0]=np.median(xx)
    Y0=3.*prof[nbin-1]-2.*prof[nbin-2]
    xx=np.array([Y0,prof[nbin-2],prof[nbin-1]])
    smoothed[nbin-1]=np.median(xx)
    return  smoothed

def EdgeCorr(nbin,rin_cm,rout_cm,em0):
    # edge correction
    mrad = [rin_cm[nbin - 1], rout_cm[nbin - 1]]
    edge0 = (mrad[0] + mrad[1]) * mrad[0] * mrad[1] / rout_cm ** 3
    edge1 = 2. * rout_cm / mrad[1] + np.arccos(rout_cm / mrad[1])
    edge2 = rout_cm / mrad[1] * np.sqrt(1. - rout_cm ** 2 / mrad[1] ** 2)
    edget = edge0 * (-1. + 2. / np.pi * (edge1 - edge2))
    j = np.where(rin_cm != 0)
    edge0[j] = (mrad[0] + mrad[1]) * mrad[0] * mrad[1] / (rin_cm[j] + rout_cm[j]) / rin_cm[j] / rout_cm[j]
    edge1[j] = rout_cm[j] / rin_cm[j] * np.arccos(rin_cm[j] / mrad[1]) - np.arccos(rout_cm[j] / mrad[1])
    edge2[j] = rout_cm[j] / mrad[1] * (
                np.sqrt(1. - rin_cm[j] ** 2 / mrad[1] ** 2) - np.sqrt(1. - rout_cm[j] ** 2 / mrad[1] ** 2))
    edget[j] = edge0[j] * (1. - 2. / np.pi * (edge1[j] - edge2[j]) / (rout_cm[j] / rin_cm[j] - 1.))
    surf = (rout_cm ** 2 - rin_cm ** 2) / (rout_cm[nbin - 1] ** 2 - rin_cm[nbin - 1] ** 2)
    corr = edget * surf * em0[nbin-1] / em0.clip(min=1e-10)
    return corr

def OP(deproj,nmc=1000):
    # Standard onion peeling
    prof=deproj.profile
    nbin=prof.nbin
    rinam=prof.bins - prof.ebins
    routam=prof.bins + prof.ebins
    area=np.pi*(routam**2-rinam**2) # full area in arcmin^2

    # Projection volumes
    if deproj.z is not None and deproj.cf is not None:
        amin2kpc = cosmo.kpc_proper_per_arcmin(deproj.z).value
        rin_cm = (prof.bins - prof.ebins)*amin2kpc*Mpc/1e3
        rout_cm = (prof.bins + prof.ebins)*amin2kpc*Mpc/1e3
        x=MyDeprojVol(rin_cm,rout_cm)
        vol=np.transpose(x.deproj_vol())
        dlum=cosmo.luminosity_distance(deproj.z).value*Mpc
        K2em=4.*np.pi*1e14*dlum**2/(1+deproj.z)**2/deproj.nhc/deproj.cf

        # Projected emission measure profiles
        em0 = prof.profile * K2em * area
        e_em0 = prof.eprof * K2em * area
        corr = EdgeCorr(nbin, rin_cm, rout_cm, em0)
    else:
        x=MyDeprojVol(rinam,routam)
        vol=np.transpose(x.deproj_vol()).T
        em0 = prof.profile * area
        e_em0 = prof.profile * area
        corr = EdgeCorr(nbin,rinam,routam)

    # Deproject and propagate error using Monte Carlo
    emres = np.repeat(e_em0,nmc).reshape(nbin,nmc) * np.random.randn(nbin,nmc) + np.repeat(em0,nmc).reshape(nbin,nmc)
    ct = np.repeat(corr,nmc).reshape(nbin,nmc)
    allres = np.linalg.solve(vol, emres * (1. - ct))
    ev0 = np.std(allres,axis=1)
    v0 = np.median(allres,axis=1)
    bsm = medsmooth(v0)

    deproj.sb = bsm
    deproj.sb_lo = bsm - ev0
    deproj.sb_hi = bsm + ev0

    deproj.dens = medsmooth(np.sign(bsm)*np.sqrt(np.abs(bsm)))
    edens = 0.5/np.sqrt(np.abs(bsm))*ev0
    deproj.dens_lo = deproj.dens - edens
    deproj.dens_hi = deproj.dens + edens


class Deproject:
    def __init__(self,z=None,profile=None,cf=None,f_abund='aspl'):
        self.profile = profile
        self.z = z
        self.samples = None
        self.cf = cf
        self.dens = None
        self.dens_lo = None
        self.dens_hi = None
        self.sb = None
        self.sb_lo = None
        self.sb_hi = None
        self.covmat = None
        self.bkg = None
        self.samples = None
        self.bkglim = None
        self.rout = None
        self.pmc = None
        self.pmcl = None
        self.pmch = None
        self.mg = None
        self.mgl = None
        self.mgh = None

        # mu_e: mean molecular weight per electron in pristine fully ionized gas with given abundance table
        # mup: mean molecular weight per particle  in pristine fully ionized gas with given abundance table
        # nhc: conversion factor from H n-density to e- n-density

        if f_abund == 'angr':
            nhc = 1 / 0.8337
            mup = 0.6125
            mu_e = 1.1738
        elif f_abund == 'aspl':
            nhc = 1 / 0.8527
            mup = 0.5994
            mu_e = 1.1548
        elif f_abund == 'grsa':
            nhc = 1 / 0.8520
            mup = 0.6000
            mu_e = 1.1555
        else:  # aspl default
            nhc = 1 / 0.8527
            mup = 0.5994
            mu_e = 1.1548
        self.nhc=nhc
        self.mup=mup
        self.mu_e=mu_e


    def Multiscale(self,backend='pymc3',nmcmc=1000,bkglim=None,back=None,samplefile=None,nrc=None,nbetas=6,depth=10):
        self.backend=backend
        self.nmcmc=nmcmc
        self.bkglim=bkglim
        self.back=back
        self.samplefile=samplefile
        self.nrc=samplefile
        self.nbetas=nbetas
        self.depth=depth
        if backend=='pymc3':
            Deproject_Multiscale_PyMC3(self,bkglim=bkglim,back=back,nmcmc=nmcmc,samplefile=samplefile,nrc=nrc,nbetas=nbetas)
        elif backend=='stan':
            Deproject_Multiscale_Stan(self,bkglim=bkglim,back=back,nmcmc=nmcmc,samplefile=samplefile,nrc=nrc,nbetas=nbetas,depth=depth)
        else:
            print('Unknown method '+backend)

    def OnionPeeling(self,nmc=1000):
        OP(self,nmc)

    def PlotDensity(self,outfile=None):
        # Plot extracted profile
        if self.profile is None:
            print('Error: No profile extracted')
            return
        if self.dens is None:
            print('Error: No density profile extracted')
            return

        kpcp = cosmo.kpc_proper_per_arcmin(self.z).value

        rkpc = self.rout * kpcp
        erkpc = self.profile.ebins * kpcp

        plt.clf()
        fig = plt.figure(figsize=(13, 10))
        ax_size = [0.14, 0.14,
                   0.83, 0.83]
        ax = fig.add_axes(ax_size)
        ax.minorticks_on()
        ax.tick_params(length=20, width=1, which='major', direction='in', right=True, top=True)
        ax.tick_params(length=10, width=1, which='minor', direction='in', right=True, top=True)
        for item in (ax.get_xticklabels() + ax.get_yticklabels()):
            item.set_fontsize(18)
        plt.xlabel('Radius [kpc]', fontsize=40)
        plt.ylabel('$n_{H}$ [cm$^{-3}$]', fontsize=40)
        plt.xscale('log')
        plt.yscale('log')

        if len(self.rout) == len(self.profile.bins):
            plt.errorbar(rkpc, self.dens, xerr=erkpc, yerr=[self.dens-self.dens_lo,self.dens_hi-self.dens], fmt='.', color='C0', elinewidth=2,
                     markersize=7, capsize=3)
        else:
            plt.plot(rkpc,self.dens,color='C0',lw=2)
        plt.fill_between(rkpc,self.dens_lo,self.dens_hi,color='C0',alpha=0.3)
        if outfile is not None:
            plt.savefig(outfile)
            plt.close()
        else:
            plt.show(block=False)

    def Density(self,rout=None):
        z = self.z
        cf = self.cf
        samples = self.samples
        prof = self.profile
        rad = prof.bins
        sourcereg = np.where(rad < self.bkglim)

        if z is not None and cf is not None:
            transf = 4. * (1. + z) ** 2 * (180. * 60.) ** 2 / np.pi / 1e-14 / self.nhc / Mpc * 1e3
            pardens = list_params_density(rad, sourcereg, z)
            if rout is None:
                sourcereg_out=sourcereg
                rout=rad
            else:
                sourcereg_out=np.where(rout < self.bkglim)
            Kdens = calc_density_operator(rout, sourcereg_out, pardens, z)
            alldens = np.sqrt(np.dot(Kdens, np.exp(samples.T)) / cf * transf)  # [0:nptfit, :]
            covmat = np.cov(alldens)
            self.covmat = covmat
            pmcd = np.median(alldens, axis=1)
            pmcdl = np.percentile(alldens, 50. - 68.3 / 2., axis=1)
            pmcdh = np.percentile(alldens, 50. + 68.3 / 2., axis=1)
            self.dens = pmcd
            self.dens_lo = pmcdl
            self.dens_hi = pmcdh
            self.rout=rout

        else:
            print('No redshift and/or conversion factor, nothing to do')

    def PlotSB(self,outfile=None):
        if self.profile is None:
            print('Error: No profile extracted')
            return
        if self.sb is None:
            print('Error: No reconstruction available')
            return
        prof=self.profile
        plt.clf()
        fig = plt.figure(figsize=(13, 10))

        ax=fig.add_axes([0.12,0.2,0.8,0.7])
        ax_res=fig.add_axes([0.12,0.1,0.8,0.1])

        ax_res.set_xlabel('Radius [arcmin]', fontsize=40)
        ax.set_ylabel('SB [counts s$^{-1}$ arcmin$^{-2}$]', fontsize=40)
        ax.set_xscale('log')
        ax.set_yscale('log')

        #ax.errorbar(prof.bins, prof.profile, xerr=prof.ebins, yerr=prof.eprof, fmt='o', color='black', elinewidth=2,
        #            markersize=7, capsize=0, mec='black', label='Bkg - subtracted Data')

        ax.errorbar(prof.bins, prof.counts / prof.area / prof.effexp, xerr=prof.ebins, yerr=prof.eprof, fmt='d',
                    color='r', elinewidth=2,
                    markersize=7, capsize=0, label='Data')
        ax.plot(prof.bins, prof.bkgprof, color='green', label='Particle background')

        # plt.errorbar(self.profile.bins, self.sb, xerr=self.profile.ebins, yerr=[self.sb-self.sb_lo,self.sb_hi-self.sb], fmt='o', color='blue', elinewidth=2,  markersize=7, capsize=0,mec='blue',label='Reconstruction')
        ax.plot(prof.bins, self.sb, color='C0', lw=2, label='Source model')
        ax.fill_between(prof.bins, self.sb_lo, self.sb_hi, color='C0', alpha=0.5)

        ax.axhline(self.bkg,color='k',label='Sky background')

        #compute SB profile without bkg subtraction to get residuals on fit
        # Set vector with list of parameters
        sourcereg = np.where(prof.bins < self.bkglim)
        pars = list_params(prof.bins, sourcereg)
        npt = len(pars)
        # Compute output deconvolved brightness profile
        if prof.psfmat is not None:
            psfmat = np.transpose(prof.psfmat)
        else:
            psfmat = np.eye(prof.nbin)
        samples=self.samples
        Ksb = calc_sb_operator_psf(prof.bins, sourcereg, pars, prof.area, prof.effexp, psfmat)
        allsb = np.dot(Ksb, np.exp(samples.T))
        bfit = np.median(np.exp(samples[:, npt]))
        pmc = np.median(allsb, axis=1) / prof.area / prof.effexp + prof.bkgprof
        pmcl = np.percentile(allsb, 50. - 68.3 / 2., axis=1) / prof.area / prof.effexp + prof.bkgprof
        pmch = np.percentile(allsb, 50. + 68.3 / 2., axis=1) / prof.area / prof.effexp + prof.bkgprof

        ax.plot(prof.bins, pmc, color='C1', lw=2, label='Total model')
        ax.fill_between(prof.bins, pmcl, pmch, color='C1', alpha=0.5)

        self.pmc=pmc
        self.pmcl=pmcl
        self.pmch=pmch

        ax.legend(loc=0,fontsize=22)

        res = (pmc * prof.area * prof.effexp - prof.counts) / (pmc * prof.area * prof.effexp)
        vmin=-0.5
        veff=np.max(np.abs(res))
        if veff > vmin:
            vmin=veff*1.2
        ax_res.scatter(prof.bins, res, color='r', lw=2)
        ax_res.axhline(0, color='k')

        ax.set_xticklabels([])
        ax_res.set_xscale('log')
        ax.legend(loc=0)

        ax.minorticks_on()
        ax.tick_params(length=20, width=1, which='major', direction='in', right=True, top=True)
        ax.tick_params(length=10, width=1, which='minor', direction='in', right=True, top=True)
        ax_res.minorticks_on()
        ax_res.tick_params(length=20, width=1, which='major', direction='in', right=True, top=True)
        ax_res.tick_params(length=10, width=1, which='minor', direction='in', right=True, top=True)
        for item in (ax.get_xticklabels() + ax.get_yticklabels()):
            item.set_fontsize(18)
        ax_res.set_xlim(ax.get_xlim())
        ax.set_ylim([0.1 * np.min(self.bkg), 1.5 * np.max(prof.counts / prof.area / prof.effexp)])
        ax_res.set_ylim([-vmin,vmin])
        if outfile is not None:
            plt.savefig(outfile)
            plt.close()
        else:
            plt.show(block=False)


    def CountRate(self,a,b,plot=True,outfile=None):
        if self.samples is None:
            print('Error: no MCMC samples found')
            return
        # Set source region
        prof = self.profile
        rad = prof.bins
        sourcereg = np.where(rad < self.bkglim)

        # Avoid diverging profiles in the center by cutting to the innermost points, if necessary
        if a<prof.bins[0]/2.:
            a = prof.bins[0]/2.

        # Set vector with list of parameters
        pars = list_params(rad, sourcereg)
        Kint = calc_int_operator(a, b, pars)
        allint = np.dot(Kint, np.exp(self.samples.T))
        medint = np.median(allint[1, :] - allint[0, :])
        intlo = np.percentile(allint[1, :] - allint[0, :], 50. - 68.3 / 2.)
        inthi = np.percentile(allint[1, :] - allint[0, :], 50. + 68.3 / 2.)
        print('Reconstructed count rate: %g (%g , %g)' % (medint, intlo, inthi))
        if plot:
            plt.clf()
            fig = plt.figure(figsize=(13, 10))
            ax_size = [0.14, 0.12,
                       0.85, 0.85]
            ax = fig.add_axes(ax_size)
            ax.minorticks_on()
            ax.tick_params(length=20, width=1, which='major', direction='in', right=True, top=True)
            ax.tick_params(length=10, width=1, which='minor', direction='in', right=True, top=True)
            for item in (ax.get_xticklabels() + ax.get_yticklabels()):
                item.set_fontsize(22)
            # plt.yscale('log')
            plt.hist(allint[1,:]-allint[0,:], bins=30)
            plt.xlabel('Count Rate [cts/s]', fontsize=40)
            plt.ylabel('Frequency', fontsize=40)
            if outfile is not None:
                plt.savefig(outfile)
                plt.close()
            else:
                plt.show(block=False)

        return  medint,intlo,inthi

    def Ncounts(self,plot=True,outfile=None):
        if self.samples is None:
            print('Error: no MCMC samples found')
            return
        # Set source region
        prof = self.profile
        rad = prof.bins
        sourcereg = np.where(rad < self.bkglim)
        area = prof.area
        exposure = prof.effexp

        if prof.psfmat is not None:
            psfmat = np.transpose(prof.psfmat)
        else:
            psfmat = np.eye(prof.nbin)

        # Set vector with list of parameters
        pars = list_params(rad, sourcereg)
        K = calc_linear_operator(rad, sourcereg, pars, area, exposure, psfmat)
        npars = len(pars[:, 0])
        K[:,npars] = 0.
        allnc = np.dot(K, np.exp(self.samples.T))
        self.rec_counts=np.median(allnc,axis=1)
        ncv = np.sum(allnc, axis=0)
        pnc = np.median(ncv)
        pncl = np.percentile(ncv, 50. - 68.3 / 2.)
        pnch = np.percentile(ncv, 50. + 68.3 / 2.)
        print('Reconstructed counts: %g (%g , %g)' % (pnc, pncl, pnch))
        if plot:
            plt.clf()
            fig = plt.figure(figsize=(13, 10))
            ax_size = [0.14, 0.12,
                       0.85, 0.85]
            ax = fig.add_axes(ax_size)
            ax.minorticks_on()
            ax.tick_params(length=20, width=1, which='major', direction='in', right=True, top=True)
            ax.tick_params(length=10, width=1, which='minor', direction='in', right=True, top=True)
            for item in (ax.get_xticklabels() + ax.get_yticklabels()):
                item.set_fontsize(22)
            # plt.yscale('log')
            plt.hist(ncv, bins=30)
            plt.xlabel('$N_{count}$', fontsize=40)
            plt.ylabel('Frequency', fontsize=40)
            if outfile is not None:
                plt.savefig(outfile)
                plt.close()
            else:
                plt.show(block=False)

        return  pnc,pncl,pnch


    # Compute Mgas within radius in kpc
    def Mgas(self,radius,plot=True,outfile=None):
        if self.samples is None or self.z is None or self.cf is None:
            print('Error: no gas density profile found')
            return
        prof = self.profile
        kpcp = cosmo.kpc_proper_per_arcmin(self.z).value
        rkpc = prof.bins * kpcp
        erkpc = prof.ebins * kpcp
        nhconv =  mh * self.mu_e * self.nhc * kpc ** 3 / msun  # Msun/kpc^3

        rad = prof.bins
        sourcereg = np.where(rad < self.bkglim)

        transf = 4. * (1. + self.z) ** 2 * (180. * 60.) ** 2 / np.pi / 1e-14 / self.nhc / Mpc * 1e3
        pardens = list_params_density(rad, sourcereg, self.z)
        Kdens = calc_density_operator(rad, sourcereg, pardens, self.z)

        # All gas density profiles
        alldens = np.sqrt(np.dot(Kdens, np.exp(self.samples.T)) / self.cf * transf)  # [0:nptfit, :]

        # Matrix containing integration volumes
        volmat = np.repeat(4. * np.pi * rkpc ** 2 * 2. * erkpc, alldens.shape[1]).reshape(len(prof.bins),alldens.shape[1])

        # Compute Mgas profile as cumulative sum over the volume
        mgas = np.cumsum(alldens * nhconv * volmat, axis=0)

        # Interpolate at the radius of interest
        f = interp1d(rkpc, mgas, axis=0)
        mgasdist = f(radius)
        mg, mgl, mgh = np.percentile(mgasdist,[50.,50.-68.3/2.,50.+68.3/2.])
        if plot:
            plt.clf()
            fig = plt.figure(figsize=(13, 10))
            ax_size = [0.14, 0.12,
                       0.85, 0.85]
            ax = fig.add_axes(ax_size)
            ax.minorticks_on()
            ax.tick_params(length=20, width=1, which='major', direction='in', right=True, top=True)
            ax.tick_params(length=10, width=1, which='minor', direction='in', right=True, top=True)
            for item in (ax.get_xticklabels() + ax.get_yticklabels()):
                item.set_fontsize(22)
            # plt.yscale('log')
            plt.hist(mgasdist, bins=30)
            plt.xlabel('$M_{gas} [M_\odot]$', fontsize=40)
            plt.ylabel('Frequency', fontsize=40)
            if outfile is not None:
                plt.savefig(outfile)
                plt.close()
            else:
                plt.show(block=False)

        return mg,mgl,mgh

    def PlotMgas(self,rout=None,outfile=None):
        if self.samples is None or self.z is None or self.cf is None:
            print('Error: no gas density profile found')
            return


        prof = self.profile
        kpcp = cosmo.kpc_proper_per_arcmin(self.z).value
        if rout is None:
            rkpc = prof.bins * kpcp
            erkpc = prof.ebins * kpcp
        else:
            rkpc = rout * kpcp
            erkpc = (rout-np.append(0,rout[:-1]))/2 * kpcp
        nhconv =  mh * self.mu_e * self.nhc * kpc ** 3 / msun  # Msun/kpc^3

        rad = prof.bins
        sourcereg = np.where(rad < self.bkglim)

        transf = 4. * (1. + self.z) ** 2 * (180. * 60.) ** 2 / np.pi / 1e-14 / self.nhc / Mpc * 1e3
        pardens = list_params_density(rad, sourcereg, self.z)
        if rout is None:
            sourcereg_out = sourcereg
            rout = rad
        else:
            sourcereg_out = np.where(rout < self.bkglim)
        Kdens = calc_density_operator(rout, sourcereg_out, pardens, self.z)

        # All gas density profiles
        alldens = np.sqrt(np.dot(Kdens, np.exp(self.samples.T)) / self.cf * transf)  # [0:nptfit, :]

        # Matrix containing integration volumes
        volmat = np.repeat(4. * np.pi * rkpc ** 2 * 2. * erkpc, alldens.shape[1]).reshape(len(rout),alldens.shape[1])


        # Compute Mgas profile as cumulative sum over the volume
        mgasdist = np.cumsum(alldens * nhconv * volmat, axis=0)


        mg, mgl, mgh = np.percentile(mgasdist,[50.,50.-68.3/2.,50.+68.3/2.],axis=1)

        self.mg=mg
        self.mgl=mgl
        self.mgh=mgh

        fig = plt.figure(figsize=(13, 10))
        ax=fig.add_subplot(111)


        ax.plot(rout, mg, color='C0', lw=2, label='Gas mass')
        ax.fill_between(rout, mgl, mgh, color='C0', alpha=0.5)


        ax.set_xscale('log')
        ax.set_yscale('log')
        ax.set_ylabel('$M_{gas} [M_\odot]$', fontsize=40)
        ax.set_xlabel('Radius [arcmin]', fontsize=40)

        ax.legend(loc=0)

        ax.minorticks_on()
        ax.tick_params(length=20, width=1, which='major', direction='in', right=True, top=True)
        ax.tick_params(length=10, width=1, which='minor', direction='in', right=True, top=True)
        for item in (ax.get_xticklabels() + ax.get_yticklabels()):
            item.set_fontsize(18)
        if outfile is not None:
            plt.savefig(outfile)
            plt.close()
        else:
            plt.show(block=False)


    def Reload(self,samplefile,bkglim=None):
        # Reload the output of a previous PyMC3 run
        samples = np.loadtxt(samplefile)
        self.samples = samples
        if self.profile is None:
            print('Error: no profile provided')
            return

        prof = self.profile
        sb = prof.profile
        rad = prof.bins
        erad = prof.ebins

        if bkglim is not None:
            self.bkglim = bkglim
        else:
            if self.bkglim is None:
                bkglim = np.max(rad + erad)
                self.bkglim = bkglim

        # Set source region
        sourcereg = np.where(rad < bkglim)

        # Set vector with list of parameters
        pars = list_params(rad, sourcereg)
        npt = len(pars)
        # Compute output deconvolved brightness profile
        Ksb = calc_sb_operator(rad, sourcereg, pars)
        allsb = np.dot(Ksb, np.exp(samples.T))
        bfit = np.median(np.exp(samples[:, npt]))
        pmc = np.median(allsb, axis=1)
        pmcl = np.percentile(allsb, 50. - 68.3 / 2., axis=1)
        pmch = np.percentile(allsb, 50. + 68.3 / 2., axis=1)

        self.sb = pmc
        self.sb_lo = pmcl
        self.sb_hi = pmch
        self.bkg = bfit

    def CSB(self,rin=40.,rout=400.,plot=True,outfile=None):
        if self.samples is None or self.z is None:
            print('Error: no profile reconstruction found')
            return
        prof = self.profile
        kpcp = cosmo.kpc_proper_per_arcmin(self.z).value

        sourcereg = np.where(prof.bins < self.bkglim)

        # Set vector with list of parameters
        pars = list_params(prof.bins, sourcereg)
        Kin = calc_int_operator(prof.bins[0]/2., rin/kpcp, pars)
        allvin = np.dot(Kin, np.exp(self.samples.T))
        Kout = calc_int_operator(prof.bins[0]/2., rout/kpcp, pars)
        allvout = np.dot(Kout, np.exp(self.samples.T))
        medcsb = np.median((allvin[1, :] - allvin[0, :]) / (allvout[1, :] - allvout[0, :]))
        csblo = np.percentile((allvin[1, :] - allvin[0, :]) / (allvout[1, :] - allvout[0, :]), 50. - 68.3 / 2.)
        csbhi = np.percentile((allvin[1, :] - allvin[0, :]) / (allvout[1, :] - allvout[0, :]), 50. + 68.3 / 2.)
        print('Surface brightness concentration: %g (%g , %g)' % (medcsb, csblo, csbhi))

        if plot:
            plt.clf()
            fig = plt.figure(figsize=(13, 10))
            ax_size = [0.14, 0.12,
                       0.85, 0.85]
            ax = fig.add_axes(ax_size)
            ax.minorticks_on()
            ax.tick_params(length=20, width=1, which='major', direction='in', right=True, top=True)
            ax.tick_params(length=10, width=1, which='minor', direction='in', right=True, top=True)
            for item in (ax.get_xticklabels() + ax.get_yticklabels()):
                item.set_fontsize(22)
            # plt.yscale('log')
            plt.hist((allvin[1, :] - allvin[0, :]) / (allvout[1, :] - allvout[0, :]), bins=30)
            plt.xlabel('$C_{SB}$', fontsize=40)
            plt.ylabel('Frequency', fontsize=40)
            if outfile is not None:
                plt.savefig(outfile)
                plt.close()
            else:
                plt.show(block=False)

        return  medcsb,csblo,csbhi


    def SaveAll(self, outfile=None):
        #####################################################
        # Function to save profile into FITS file
        # First extension is data
        # Second extension is density
        # Third extension is Mgas
        # Forth extension is PSF
        #####################################################
        if outfile is None:
            print('No output file name given')
            return
        else:
            hdul = fits.HDUList([fits.PrimaryHDU()])
            if self.profile is not None:
                cols = []
                cols.append(fits.Column(name='RADIUS', format='E', unit='arcmin', array=self.profile.bins))
                cols.append(fits.Column(name='WIDTH', format='E', unit='arcmin', array=self.profile.ebins))
                cols.append(fits.Column(name='SB', format='E', unit='cts s-1 arcmin-2', array=self.profile.profile))
                cols.append(fits.Column(name='ERR_SB', format='E', unit='cts s-1 arcmin-2', array=self.profile.eprof))
                if self.profile.counts is not None:
                    cols.append(fits.Column(name='COUNTS', format='I', unit='', array=self.profile.counts))
                    cols.append(fits.Column(name='AREA', format='E', unit='arcmin2', array=self.profile.area))
                    cols.append(fits.Column(name='EFFEXP', format='E', unit='s', array=self.profile.effexp))
                    cols.append(fits.Column(name='BKG', format='E', unit='cts s-1 arcmin-2', array=self.profile.bkgprof))
                    cols.append(fits.Column(name='BKGCOUNTS', format='E', unit='', array=self.profile.bkgcounts))
                cols = fits.ColDefs(cols)
                tbhdu = fits.BinTableHDU.from_columns(cols, name='DATA')
                hdr = tbhdu.header
                hdr['X_C'] = self.profile.cx + 1
                hdr['Y_C'] = self.profile.cy + 1
                hdr.comments['X_C'] = 'X coordinate of center value'
                hdr.comments['Y_C'] = 'Y coordinate of center value'
                hdr['RA_C'] = self.profile.cra
                hdr['DEC_C'] = self.profile.cdec
                hdr.comments['RA_C'] = 'Right ascension of center value'
                hdr.comments['DEC_C'] = 'Declination of center value'
                hdr['COMMENT'] = 'Written by pyproffit (Eckert et al. 2011)'
                hdul.append(tbhdu)
            if self.pmc is not None:
                cols = []
                cols.append(fits.Column(name='RADIUS', format='E', array=self.profile.bins))
                cols.append(fits.Column(name='SB_MODEL_TOT', format='E', array=self.pmc))
                cols.append(fits.Column(name='SB_MODEL_TOT_L', format='E', array=self.pmcl))
                cols.append(fits.Column(name='SB_MODEL_TOT_H', format='E', array=self.pmch))
                cols.append(fits.Column(name='SB_MODEL', format='E', array=self.sb))
                cols.append(fits.Column(name='SB_MODEL_L', format='E', array=self.sb_lo))
                cols.append(fits.Column(name='SB_MODEL_H', format='E', array=self.sb_hi))
                cols = fits.ColDefs(cols)
                tbhdu = fits.BinTableHDU.from_columns(cols, name='SB_MODEL')
                hdr = tbhdu.header
                hdr['BACKEND'] = self.backend
                hdr['N_MCMC'] = self.nmcmc
                hdr['BKGLIM'] = self.bkglim
                hdr['BACK'] = self.back
                hdr['SAMPLEFILE'] = self.samplefile
                hdr['N_RC'] = self.nrc
                hdr['N_BETAS'] = self.nbetas
                hdr['DEPTH'] = self.depth
                hdul.append(tbhdu)
            if self.dens is not None:
                cols = []
                cols.append(fits.Column(name='RADIUS', format='E', array=self.rout))
                cols.append(fits.Column(name='DENSITY', format='E', array=self.dens))
                cols.append(fits.Column(name='DENSITY_L', format='E', array=self.dens_lo))
                cols.append(fits.Column(name='DENSITY_H', format='E', array=self.dens_hi))
                if self.mg is not None:
                    cols.append(fits.Column(name='MGAS', format='E', array=self.mg))
                    cols.append(fits.Column(name='MGAS_L', format='E', array=self.mgl))
                    cols.append(fits.Column(name='MGAS_H', format='E', array=self.mgh))
                cols = fits.ColDefs(cols)
                tbhdu = fits.BinTableHDU.from_columns(cols, name='DENSITY')
                hdul.append(tbhdu)
            if self.profile.psfmat is not None:
                psfhdu = fits.ImageHDU(self.profile.psfmat, name='PSF')
                hdul.append(psfhdu)
            hdul.writeto(outfile, overwrite=True)



