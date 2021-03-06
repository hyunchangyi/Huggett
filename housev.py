# -*- coding: utf-8 -*-
"""
Jul. 7, 2015, Hyun Chang Yi
Huggett (1996) "Wealth distribution in life-cycle economies," Journal of Monetary
Economics, 38(3), 469-494.
"""

from scipy.interpolate import interp1d
from scipy.optimize import fsolve, minimize_scalar, broyden1, broyden2
from numpy import linspace, mean, array, zeros, absolute, loadtxt, dot, prod, int,\
                    genfromtxt, sum, argmax, tile, concatenate, ones, log, \
                    unravel_index, cumsum, meshgrid, atleast_2d, where, newaxis,\
                    maximum, transpose
from matplotlib import pyplot as plt
from datetime import datetime
import time
import pickle
import os
from platform import system
from multiprocessing import Process, Lock, Manager
from multiprocessing.sharedctypes import Value, Array, RawArray
from ctypes import Structure, c_double


class params:
    """ This class is just a "struct" to hold the collection of PARAMETER values """
    def __init__(self, T=1, alpha=0.36, delta=0.08, tau=0.2378, theta=0.1, zeta=0.3,
        beta=0.994, sigma=1.5, W=45, R=34, a0 = 0, ng_init=1.012, ng_term=1.0-0.012,
        aH=50.0, aL=0.0, aN=200, hN=5, psi=0.1, phi=0.5, dti=0.5, ltv=0.7, tcost=0.02, Hs=7,
        tol=1e-2, eps=0.2, neg=-1e10, gs=1.5):
        if T==1:
            ng_term = ng_init
        self.alpha, self.zeta, self.delta, self.tau = alpha, zeta, delta, tau
        self.theta, self.psi = theta, psi
        self.tcost, self.dti, self.ltv = tcost, dti, ltv
        self.beta, self.sigma = beta, sigma
        self.R, self.W, self.T = R, W, T
        self.aH, self.aL = aH, aL
        am = [-aH*linspace(0,1,aN)**gs][0][int(-aN*aL/(aH-aL)):0:-1]
        ap = aH*linspace(0,1,aN)**gs
        self.aa = concatenate((am,ap))
        self.aN = len(self.aa)
        # self.aa = aL+aH*linspace(0,1,aN)
        self.phi, self.tol, self.neg, self.eps = phi, tol, neg, eps
        self.hh = linspace(0.1,1.0,hN)   # hh = [0, 1, 2, 3, 4]
        self.hN = hN
        """ LOAD PARAMETERS : SURVIVAL PROB., PRODUCTIVITY TRANSITION PROB. AND ... """
        if system() == 'Windows':
            self.sp = sp = loadtxt('parameters\sp.txt', delimiter='\n')  # survival probability
            self.muz = genfromtxt('parameters\muz.csv', delimiter=',')  # initial distribution of productivity
            self.pi = genfromtxt('parameters\pi.csv', delimiter=',')  # productivity transition probability
            self.ef = genfromtxt('parameters\ef.csv', delimiter=',')
        else:
            self.sp = sp = loadtxt('parameters/sp.txt', delimiter='\n')  # survival probability
            self.muz = genfromtxt('parameters/muz.csv', delimiter=',')  # initial distribution of productivity
            self.pi = genfromtxt('parameters/pi.csv', delimiter=',')  # productivity transition probability
            self.ef = genfromtxt('parameters/ef.csv', delimiter=',')
        self.zN = self.pi.shape[0]
        self.mls = self.ef.shape[0]
        """ CALCULATE POPULATIONS OVER THE TRANSITION PATH """
        m0 = array([prod(sp[:y+1])/ng_init**y for y in range(self.mls)], dtype=float)
        m1 = array([prod(sp[:y+1])/ng_term**y for y in range(self.mls)], dtype=float)
        self.pop = array([m1*ng_term**t for t in range(T)], dtype=float)
        for t in range(min(T,self.mls-1)):
            self.pop[t,t+1:] = m0[t+1:]*ng_init**t
        """ House Supply OVER THE TRANSITION PATH """
        self.Hs = Hs*ones(T)


    def print_params(self):
        print '\n===================== Parameters ====================='
        if self.T==1:
            print 'Finding Steady State ... \n'
        else:
            print 'Finding Transition Path over %i periods ... \n'%(self.T)
        print 'Liquid Asset: [%i'%(self.aL),', %i]'%(self.aH),' with Grid Size %i'%(self.aN)
        print '       House: [%2.2f'%(self.hh[0]),', %2.2f]'%(self.hh[-1]),' with Grid Size %i'%(self.hN)
        if self.T==1:
            print 'House Supply: %2.2f'%(self.Hs[0])
        else:
            print 'House Supply: from %2.2f'%(self.Hs[0]), 'to %2.2f'%(self.Hs[-1]),' over the Transition Path'
        if self.T>1:
            print 'Populations : from %3.2f'%(sum(self.pop[0])), 'to %3.2f'%(sum(self.pop[-1]))
        print '\n','psi  :%2.2f'%(self.psi), ' tol  :%2.2f'%(self.tol), ' eps:%2.2f'%(self.eps)\
                , ' phi:%2.2f'%(self.phi), ' tcost:%2.2f'%(self.tcost), '\n'\
             ,'delta:%2.2f'%(self.delta), ' alpha:%2.2f'%(self.alpha)\
                , ' dti:%2.2f'%(self.dti), ' ltv:%2.2f'%(self.ltv), ' beta :%2.2f'%(self.beta)
        print '====================================================== \n'


class state:
    """ This class is just a "struct" to hold the collection of primitives defining
    an economy in which one or multiple generations live """
    def __init__(self, params, r_init=0.05, r_term=0.05, Bq_init=0, Bq_term=0,
        q_init=4.6, q_term=3.3):
        # tr = 0.429, tw = 0.248, zeta=0.5, gy = 0.195, in Section 9.3. in Heer/Maussner
        """tr, tw and tb are tax rates on capital return, wage and tax for pension.
        tb is determined by replacement ratio, zeta, and other endogenous variables.
        gy is ratio of government spending over output.
        Transfer from government to households, Tr, is determined endogenously"""
        self.zeta = params.zeta
        self.psi = params.psi # this parameter is used for plot_lp
        self.delta = delta = params.delta
        self.alpha = alpha = params.alpha
        self.T = T = params.T
        self.phi, self.tol, self.eps = params.phi, params.tol, params.eps
        self.aN = aN = params.aN
        self.aa = aa = params.aa
        self.hh = hh = params.hh
        self.hN = hN = params.hN
        self.Hs = params.Hs
        """ SURVIVAL PROB., PRODUCTIVITY TRANSITION PROB. AND ... """
        self.sp = sp = params.sp
        self.pi = pi = params.pi
        # muz[y] : distribution of productivity of y-yrs agents
        self.muz = muz = params.muz
        self.ef = ef = params.ef
        self.zN = zN = params.zN
        self.mls = mls = params.mls
        """ CALCULATE POPULATIONS OVER THE TRANSITION PATH """
        self.pop = params.pop
        """Construct containers for market prices, tax rates, pension, bequest"""
        if T==1:
            r_term, q_term, Bq_term = r_init, q_init, Bq_init
        self.theta = params.theta*ones(T)
        self.tau = params.tau*ones(T)
        self.r = r_term*ones(T)
        self.q = q_term*ones(T)
        self.Bq = Bq_term*ones(T)
        self.r[0:T-mls] = linspace(r_init,r_term,T-mls)
        self.q[0:T-mls] = linspace(q_init,q_term,T-mls)
        self.Bq[0:T-mls] = linspace(Bq_init,Bq_term,T-mls)
        self.pr, self.L, self.K, self.w, self.b = [zeros(T) for i in range(5)]
        for t in range(T):
            # pr = population of retired agents
            self.pr[t] = sum(self.pop[t,45:])
            # L = labor supply in efficiency unit
            self.L[t] = sum([muz[y].dot(ef[y])*self.pop[t,y] for y in range(mls)])
            self.K[t] = ((self.r[t]+delta)/alpha)**(1.0/(alpha-1.0))*self.L[t]
            self.w[t] = ((self.r[t]+delta)/alpha)**(alpha/(alpha-1.0))*(1.0-alpha)
            self.b[t] = self.theta[t]*self.w[t]*self.L[t]/self.pr[t]
        self.Hd = zeros(T)
        self.r1 = zeros(T)
        self.K1 = zeros(T)
        self.Bq1 = zeros(T)
        """ PRICES, PENSION BENEFITS, BEQUESTS AND TAXES
        that are observed by households """
        self.prices = array([self.r, self.w, self.q, self.b, self.Bq, self.theta, self.tau])
        self.mu = [zeros((mls,hN,zN,aN)) for t in range(T)]


    def aggregate(self, vmu):
        """Aggregate Capital, Labor in Efficiency unit and Bequest over all cohorts"""
        T, mls, alpha, delta, zeta = self.T, self.mls, self.alpha, self.delta, self.zeta
        aa, pop, sp, zN, aN, hN, hh = self.aa, self.pop, self.sp, self.zN, self.aN, self.hN, self.hh
        spr = (1-sp)/sp
        my = lambda x: x if x < T-1 else -1
        self.mu = [array(vmu[t]).reshape(mls,hN,zN,aN) for t in range(len(vmu))]
        self.Hd = zeros(T)
        self.K1 = zeros(T)
        self.Bq1 = zeros(T)
        """Aggregate all cohorts' capital and labor supply at each year"""
        for t in range(T):
            for y in range(mls):
                k1 = sum(self.mu[my(t+y)][-(y+1)],(0,1)).dot(aa)*pop[t,-(y+1)]
                hd = sum(self.mu[my(t+y)][-(y+1)],(1,2)).dot(hh)*pop[t,-(y+1)]
                bq1 = (k1 + hd*self.q[t])*spr[-(y+1)]*(1-zeta)/sum(pop[t])
                self.K1[t] += k1
                self.Hd[t] += hd
                self.Bq1[t] += bq1
        self.r1 = alpha*(self.K1/self.L)**(alpha-1.0)-delta


    def update_prices(self):
        """ Update market prices, w and r, and many others according to new
        aggregate capital and labor paths for years 0,...,T from last iteration """
        alpha, delta = self.alpha, self.delta
        self.r = self.phi*self.r + (1-self.phi)*self.r1
        self.K = ((self.r+delta)/alpha)**(1.0/(alpha-1.0))*self.L
        self.w = ((self.r+delta)/alpha)**(alpha/(alpha-1.0))*(1.0-alpha)
        self.b = self.theta*self.w*self.L/self.pr
        self.prices[0] = self.r
        self.prices[1] = self.w
        self.prices[3] = self.b
        self.Bq = self.phi*self.Bq + (1-self.phi)*self.Bq1
        self.prices[4] = self.Bq
        self.q = self.q*(1+self.eps*(self.Hd-self.Hs))
        self.prices[2] = self.q
        # array([self.r, self.w, self.q, self.b, self.Bq, self.theta, self.tau])


    def update_Bq(self):
        """ Update the amount of bequest given to households """
        self.Bq = self.phi*self.Bq + (1-self.phi)*self.Bq1
        self.prices[4] = self.Bq


    def update_q(self):
        """ Update the amount of bequest given to households """
        self.q = self.q*(1+self.eps*(self.Hd-self.Hs))
        self.prices[2] = self.q


    def converged(self):
        return max(absolute(self.K - self.K1))/max(self.K) < self.tol \
                and max(absolute(self.Hd - self.Hs))/max(self.Hd) < self.tol


    def print_prices(self, n=0, t=0):
        print "n=%2i"%(n)," t=%3i"%(t),"r=%2.2f%%"%(self.r[t]*100),"Pop.=%3.1f"%(sum(self.pop[t])),\
              "Ks=%3.1f,"%(self.K1[t]),"q=%2.1f,"%(self.q[t]),"Hd=%3.1f,"%(self.Hd[t]),\
              "Bq=%2.2f," %(self.Bq1[t])


    def plot(self, t=0, yi=0, yt=78, ny=10):
        """plot life-path of aggregate capital accumulation and house demand"""
        mls = self.mls
        pop, aa, hh, aN, hN = self.pop, self.aa, self.hh, self.aN, self.hN
        mu = self.mu[t]
        a = zeros(mls)
        h = zeros(mls)
        ap = zeros(mls)
        hp = zeros(mls)
        al = zeros(aN)
        hl = zeros(hN)
        """Aggregate all cohorts' capital and labor supply at each year"""
        for y in range(mls):
            ap[y] = sum(mu[y],(0,1)).dot(aa)*pop[t,y]
            hp[y] = sum(mu[y],(1,2)).dot(hh)*pop[t,y]
            a[y] = sum(mu[y],(0,1)).dot(aa)
            h[y] = sum(mu[y],(1,2)).dot(hh)
            al += sum(mu[y],(0,1))*pop[t,y]
            hl += sum(mu[y],(1,2))*pop[t,y]
        title = 'psi=%2.2f'%(self.psi) + ' aN=%2.2f'%(self.aN) +' hN=%2.2f'%(self.hN) +\
                ' r=%2.2f%%'%(self.r[t]*100) + ' q=%2.2f'%(self.q[t]) + \
                ' K=%2.1f'%(self.K[t]) + ' Hd=%2.1f'%(self.Hd[t])
        filename = title + '.png'
        fig = plt.figure(facecolor='white')
        plt.rcParams.update({'font.size': 8})
        # matplotlib.rcParams.update({'font.size': 22})
        ax = fig.add_subplot(111)
        ax1 = fig.add_subplot(231)
        ax2 = fig.add_subplot(234)
        ax3 = fig.add_subplot(232)
        ax4 = fig.add_subplot(235)
        ax5 = fig.add_subplot(233)
        ax6 = fig.add_subplot(236)
        fig.subplots_adjust(hspace=.5, wspace=.3, left=None, right=None, top=None, bottom=None)
        ax.spines['top'].set_color('none')
        ax.spines['bottom'].set_color('none')
        ax.spines['left'].set_color('none')
        ax.spines['right'].set_color('none')
        ax.tick_params(labelcolor='w', top='off', bottom='off', left='off', right='off')
        ax1.plot(range(mls),ap,label='aggregate')
        ax1.plot(range(mls),a,label='per capita')
        ax2.plot(range(mls),hp,label='aggregate')
        ax2.plot(range(mls),h,label='per capita')
        for y in linspace(yi,yt,ny).astype(int):
            ax3.plot(aa,sum(mu[y],(0,1)),label='age %i'%(y))
        for y in linspace(yi,yt,ny).astype(int):
            ax4.plot(hh,sum(mu[y],(1,2)),label='age %i'%(y))
        ax5.plot(cumsum(al)/sum(al),cumsum(aa*al)/sum(aa*al),".")
        ax6.plot(cumsum(hl)/sum(hl),cumsum(hh*hl)/sum(hh*hl),".")
        # ax1.legend(bbox_to_anchor=(0.9,1.0),loc='center',prop={'size':8})
        ax1.legend(prop={'size':7})
        ax2.legend(prop={'size':7})
        ax3.legend(prop={'size':7})
        ax4.legend(prop={'size':7})
        # ax3.axis([0, 15, 0, 0.1])
        ax5.axis([0, 1, 0, 1])
        ax6.axis([0, 1, 0, 1])
        # ax4.axis([0, 80, 0, 1.0])
        ax1.set_xlabel('Age')
        ax2.set_xlabel('Age')
        ax3.set_xlabel('Asset Size')
        ax4.set_xlabel('House Size')
        ax5.set_xlabel('Cum. Share of Agents from Lower to Higher')
        ax6.set_xlabel('Cum. Share of Agents from Lower to Higher')
        ax5.set_ylabel('Cum. Share of Asset Occupied')
        ax6.set_ylabel('Cum. Share of House Occupied')
        ax.set_title(title, y=1.08)
        ax1.set_title('Life-Cycle Liquid Asset Accumulation')
        ax2.set_title('Life-Cycle House Size')
        ax3.set_title('Dist. of Liquid Asset w/i Cohort')
        ax4.set_title('Dist. of House Size w/i Cohort')
        ax5.set_title('Lorenz Curve for Liquid Asset')
        ax6.set_title('Lorenz Curve for House')
        if system() == 'Windows':
            path = 'D:\Huggett\Figs'
        else:
            path = '/Users/hyunchangyi/GitHub/Huggett/Figs'
        fullpath = os.path.join(path, filename)
        fig.savefig(fullpath)
        # ax4.axis([0, 80, 0, 1.1])
        plt.show()


class cohort:
    """ This class is just a "struct" to hold the collection of primitives defining
    a generation """
    def __init__(self, params, y=-1, a0 = 0):
        self.beta, self.sigma, self.psi = params.beta, params.sigma, params.psi
        self.R, self.W, self.y = params.R, params.W, y
        # self.mls = mls = (y+1 if (y >= 0) and (y <= W+R-2) else W+R) # mls is maximum life span
        self.aN = aN = params.aN
        self.aa = aa = params.aa
        self.a0_id = where(aa >= 0)[0][0]   # agents start their life with asset aa[a0_id]
        self.hh = hh = params.hh
        self.hN = hN = params.hN
        self.tol, self.neg = params.tol, params.neg
        self.tcost = params.tcost
        self.ltv = params.ltv
        """ SURVIVAL PROB., PRODUCTIVITY TRANSITION PROB. AND ... """
        self.sp = sp = params.sp
        self.pi = pi = params.pi
        # muz[y] : distribution of productivity of y-yrs agents
        self.muz = muz = params.muz
        self.ef = ef = params.ef
        self.zN = zN = params.zN
        self.mls = mls = params.mls
        """ container for value function and expected value function """
        # v[y,h,j,i] is the value of an y-yrs-old agent with asset i and productity j, house h
        self.v = zeros((mls,hN,zN,aN))
        """ container for policy functions """
        self.a = zeros((mls,hN,zN,aN))
        self.h = zeros((mls,hN,zN,aN))
        self.c = zeros((mls,hN,zN,aN))
        """ distribution of agents w.r.t. age, productivity and asset
        for each age, distribution over all productivities and assets add up to 1 """
        self.vmu = zeros(mls*hN*zN*aN)


    def optimalpolicy(self, prices):
        """ Given prices, transfers, benefits and tax rates over one's life-cycle,
        value and decision functions are calculated ***BACKWARD*** """
        aa, hh = self.aa, self.hh
        t = prices.shape[1]
        if t < self.mls:
            d = self.mls - t
            prices = concatenate((tile(array([prices[:,0]]).T,(1,d)),prices), axis=1)
        [r, w, q, b, Bq, theta, tau] = prices
        ef, mls, R, aN, zN, hN = self.ef, self.mls, self.R, self.aN, self.zN, self.hN
        sigma, psi, beta = self.sigma, self.psi, self.beta
        sp, pi, tcost, ltv, neg = self.sp, self.pi, self.tcost, self.ltv, self.neg
        # ev[y,nh,j,ni] is the expected value when next period asset ni and house hi
        ev = zeros((mls,hN,zN,aN))
        """ inline functions: utility and income adjustment by trading house """
        util = lambda c, h: (c*h**psi)**(1-self.sigma)/(1-self.sigma)
        # util = lambda c, h: self.neg if c <= 0 else (c*h**psi)**(1-self.sigma)/(1-self.sigma)
        hinc = lambda h, nh, q: (h-nh)*q - tcost*h*q*(h!=nh)
        """ y = -1 : just before the agent dies """
        for h in range(hN):
            for z in range(zN):
                c = aa*(1+(1-tau[-1])*r[-1]) + hinc(hh[h],hh[0],q[-1])\
                        + w[-1]*ef[-1,z]*(1-theta[-1]-tau[-1]) + b[-1] + Bq[-1]
                c[c<=0.0] = 1e-10
                self.c[-1,h,z] = c
                self.v[-1,h,z] = util(c,hh[h])
            ev[-1,h] = pi.dot(self.v[-1,h])
        """ y = -2, -3,..., -60 """
        NH = hh[newaxis,:,newaxis,newaxis]
        NA = aa[newaxis,newaxis,newaxis,:]
        CA = aa[newaxis,newaxis,:,newaxis]
        for y in range(-2, -(mls+1), -1):
            EF = ef[y][:,newaxis,newaxis,newaxis]
            LTV = neg*(-ltv*NH*q[y] > NA)
            for h in range(hN):
                c = w[y]*EF*(1-theta[y]-tau[y]) + hinc(hh[h],NH,q[y]) \
                    + (CA*(1+(1-tau[y])*r[y]) + b[y]*(y>=-R) + Bq[y]) - NA
                c[c<=0.0] = 1e-10
                vt = util(c,hh[h]) + beta*sp[y+1]*transpose(ev[y+1],(1,0,2))[:,:,newaxis,:] + LTV
                for z in range(zN):
                    for a in range(aN):
                        """ find optimal pairs of house and asset """
                        self.h[y,h,z,a], self.a[y,h,z,a] \
                            = unravel_index(vt[z,:,a,:].argmax(),vt[z,:,a,:].shape)
                        self.v[y,h,z,a] = vt[z,self.h[y,h,z,a],a,self.a[y,h,z,a]]
                        # print 'optimal nh and na:', y,h,self.h[y,h,z,a], self.a[y,h,z,a]
                ev[y,h] = pi.dot(self.v[y,h])
        """ find distribution of agents w.r.t. age, productivity and asset """
        self.vmu *= 0
        mu = self.vmu.reshape(mls,hN,zN,aN)
        mu[0,0,:,self.a0_id] = self.muz[0]
        for y in range(1,mls):
            for h in range(hN):
                for z in range(zN):
                    for a in range(aN):
                        mu[y,self.h[y-1,h,z,a],:,self.a[y-1,h,z,a]] += mu[y-1,h,z,a]*pi[z]


"""The following are procedures to get steady state of the economy using direct
age-profile iteration and projection method"""


def fss(ng=1.012, N=5, psi=0.2, delta=0.08, aN=30, aL=-10, aH=40, Hs=10, hN=3, tol=0.01,
        alpha=0.36, tau=0.2378, theta=0.1, zeta=0.3, phi=0.75, eps=0.075,
        beta=0.994, sigma=1.5, dti=0.5, ltv=0.7, tcost=0.02, gs=2.0):
    """Find Old and New Steady States with population growth rates ng and ng1"""
    start_time = datetime.now()
    params0 = params(T=1, ng_init=ng, psi=psi, delta=delta, aN=aN, aL=aL, aH=aH, Hs=Hs,
                    hN=hN, tol=tol, eps=eps, alpha=alpha, beta=beta, sigma=sigma, phi=phi,
                    dti=dti, ltv=ltv, tcost=tcost, gs=gs)
    params0.print_params()
    c = cohort(params0)
    k = state(params0)
    converged = lambda k: max(absolute(k.Bq - k.Bq1)) < k.tol \
                            and max(absolute(k.Hd - k.Hs)) < k.tol
    for n in range(N):
        c.optimalpolicy(k.prices)
        k.aggregate([c.vmu])
        # while True:
        #     k.update_Bq()
        #     k.update_q()
        #     if converged(k):
        #         break
        #     c.optimalpolicy(k.prices)
        #     k.aggregate([c.vmu])
        #     print 'Hs and Hd, diff', k.Hd, k.Hs, max(absolute(k.Hd - k.Hs))
        #     print "n=%i" %(n+1),"r=%2.3f" %(k.r),"r1=%2.3f" %(k.r1),\
        #             "K=%2.3f," %(k.K),"K1=%2.3f," %(k.K1),"q=%2.3f," %(k.q),\
        #             "Hd=%2.3f," %(k.Hd),"Bq1=%2.3f," %(k.Bq1)
        k.print_prices(n=n+1)
        k.update_prices()
        if k.converged():
            print 'Economy Converged to SS! in',n+1,'iterations with', k.tol
            break
        if n >= N-1:
            print 'Economy Not Converged in',n+1,'iterations with', k.tol
            break
    end_time = datetime.now()
    print('Duration: {}'.format(end_time - start_time))
    return k, c


#병렬처리를 위한 for loop 내 로직 분리
def transition_sub1(t,mu,prices,mu_t,params):
    c = cohort(params)
    T = params.T
    mls = params.mls
    if t < T-1:
        c.optimalpolicy(prices.T[max(t-mls+1,0):t+1].T)
    else:
        c.vmu = mu_t
    for i in range(c.mls*c.hN*c.zN*c.aN):
        mu[i] = c.vmu[i]


def tran(N=20, TP=320, ng_i=1.012, ng_t=1.0, psi=0.5, delta=0.08,
        aN=50, aL=-10, aH=40, Hs=10, hN=3, tol=0.05,
        alpha=0.36, tau=0.2378, theta=0.1, zeta=0.3, phi=0.75, eps=0.075,
        beta=0.994, sigma=1.5, dti=0.5, ltv=0.7, tcost=0.02, gs=2.0):
    k_i, c_i = fss(ng=ng_i, psi=psi, delta=delta, aN=aN, aL=aL, aH=aH, Hs=Hs,
                    hN=hN, tol=tol, eps=eps, alpha=alpha, beta=beta, sigma=sigma, phi=phi,
                    dti=dti, ltv=ltv, tcost=tcost, gs=gs)
    k_t, c_t = fss(ng=ng_t, psi=psi, delta=delta, aN=aN, aL=aL, aH=aH, Hs=Hs,
                    hN=hN, tol=tol, eps=eps, alpha=alpha, beta=beta, sigma=sigma, phi=phi,
                    dti=dti, ltv=ltv, tcost=tcost, gs=gs)
    params_tp = params(T=TP, ng_init=ng_i, ng_term=ng_t,
                    psi=psi, delta=delta, aN=aN, aL=aL, aH=aH, Hs=Hs,
                    hN=hN, tol=tol, eps=eps, alpha=alpha, beta=beta, sigma=sigma, phi=phi,
                    dti=dti, ltv=ltv, tcost=tcost, gs=gs)
    params_tp.print_params()
    k_tp = state(params_tp, r_init=k_i.r, r_term=k_t.r, q_init=k_i.q, q_term=k_t.q,
                            Bq_init=k_i.Bq, Bq_term=k_t.Bq)
    mu_len = c_t.mls*c_t.hN*c_t.zN*c_t.aN
    """Generate mu of TP cohorts who die in t = 0,...,T-1 with initial asset g0.apath[-t-1]"""
    mu_tp = [RawArray(c_double, mu_len) for t in range(TP)]
    for n in range(N):
        start_time = datetime.now()
        print '\n','multiprocessing :'+str(n)+' is in progress : {} \n'.format(start_time)
        jobs = []
        for t, mu in enumerate(mu_tp):
            # transition_sub1(c,k_tp.prices,c_t.mu)
            p = Process(target=transition_sub1, args=(t,mu,k_tp.prices,c_t.vmu,params_tp))
            p.start()
            jobs.append(p)
            #병렬처리 개수 지정 20이면 20개 루프를 동시에 병렬로 처리
        # for p in jobs:
        #     p.join()
        #     jobs=[]
            if len(jobs) % 8 == 0:
                for p in jobs:
                    p.join()
                    jobs=[]
        if len(jobs) > 0:
            for p in jobs:
                p.join()
        k_tp.aggregate(mu_tp)
        for t in [0, int(TP/4), int(TP/2), int(3*TP/4), TP-1]:
            k_tp.print_prices(n=n+1,t=t)
        k_tp.update_prices()
        end_time = datetime.now()
        print 'transition ('+str(n)+') loop: {}'.format(end_time - start_time)
        if k_tp.converged():
            print 'Transition Path Converged! in', n+1,'iterations.'
            break
        if n >= N-1:
            print 'Transition Path Not Converged! in', n+1,'iterations.'
            break
    return k_tp, mu_tp


# if __name__ == '__main__':
    start_time = datetime.now()
    k, mu = tran()
    end_time = datetime.now()
    print 'Total Duration: {}'.format(end_time - start_time)
    plt.plot(k.r)
    plt.show()
