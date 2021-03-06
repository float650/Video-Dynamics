import numpy as np
from matplotlib import pyplot as pp
import theano
import theano.tensor as T

import cPickle as cp

import sys
sys.path.insert(0, '../models')

from LDmodel_2_vec import LDmodel

import math

f=open('../vid3.cpl','rb')
vid=cp.load(f)
f.close()

vid=np.asarray(vid,dtype='float32')
vid=vid-np.mean(vid,axis=0)

vid=1.0*vid/np.mean(np.abs(vid))

nt,nx=vid.shape
print vid.shape
ns=20
npcl=200

nsamps=20
lrate=2e-5

npred=1000

xdata=theano.shared(vid)

xvar=0.1

model=LDmodel(nx, ns, npcl, xvar=xvar)

idx=T.lscalar()
x1=T.fvector()
x2=T.fvector()

#norm, eng, ssmp, sprd, Wx, updates0=model.forward_filter_step(x)
#norm, eng, updates0=model.forward_filter_step(x)
#inference_step=theano.function([x],[norm,eng,ssmp,sprd,Wx],updates=updates0,allow_input_downcast=True)
#inference_step=theano.function([x],[norm,eng],updates=updates0,allow_input_downcast=True)

#hsmps, updates0=model.forward_filter_step(x1)
#inference_step=theano.function([idx],hsmps,
								#updates=updates0,
								#givens={x1: xdata[idx,:]},
								#allow_input_downcast=True)
								
updates0=model.forward_filter_step(x1)
inference_step=theano.function([idx],None,
								updates=updates0,
								givens={x1: xdata[idx,:]},
								allow_input_downcast=True)

ess=model.get_ESS()
get_ESS=theano.function([],ess)

updates1=model.resample()
resample=theano.function([],updates=updates1)

lr=T.fscalar(); nsmps=T.lscalar()

nrg, updates2 = model.update_params(x1, x2, nsmps, lr)
learn_step=theano.function([idx,nsmps,lr],[nrg],
							updates=updates2,
							givens={x1: xdata[idx-1,:], x2: xdata[idx,:]},
							allow_input_downcast=True)

nps=T.lscalar()
sps, xps, updates3 = model.simulate_forward(nps)
predict=theano.function([nps],[sps,xps],updates=updates3,allow_input_downcast=True)


plr=T.fscalar()
pnsteps=T.lscalar()
ploss, updates4 = model.update_proposal_distrib(pnsteps,plr)
update_prop=theano.function([pnsteps, plr],ploss,updates=updates4,
							allow_input_downcast=True,
							on_unused_input='ignore')

new_lrs=T.fvector()
updates5 = model.set_rel_lrates(new_lrs)
set_rel_lrates=theano.function([new_lrs],[],updates=updates5,
							allow_input_downcast=True)

e_hist=[]
ess_hist=[]
s_hist=[]
r_hist=[]
l_hist=[]
w_hist=[]
ploss_hist=[0.0]

th=[]

resample_counter=0
learn_counter=0
for epoch in range(4):
	for i in range(nt-1):
		
		#normalizer,energies,ssamps,spreds,WTx=inference_step(vec)
		#normalizer,energies=inference_step(x)
		#h_samps=inference_step(i)
		inference_step(i)
		
		#pp.scatter(ssamps[:,0],ssamps[:,1],color='b')
		#pp.scatter(spreds[:,0],spreds[:,1],color='r')
		#pp.scatter(WTx[0],WTx[1],color='g')
		
		#pp.hist(energies,20)
		#pp.show()
		
		#print h_samps
		
		
		ESS=get_ESS()
		ess_hist.append(ESS)
		learn_counter+=1
		resample_counter+=1
		
		if resample_counter>0 and learn_counter>10:
			energy=learn_step(i,nsamps, lrate)
			e_hist.append(energy)
			learn_counter=0
			pl=update_prop(800,1e-7)
			#pp.plot(pl)
			#pp.show()
			ploss_hist.append(pl)
			l_hist.append(1)
			lrate=lrate*0.9999
		else:
			l_hist.append(0)
		
		if i%1000==0:	
			#print normalizer
			
			print 'Iteration ', i+nt*epoch, ' ================================'
			print 'ESS: ', ESS
			#print '\nParameters'
			#print 'M'
			#print model.M.get_value()
			#print 'W'
			#print model.W.get_value()
			#print 'b'
			print np.exp(model.ln_b.get_value())
			print '\nMetaparameters:'
			print 'Proposal loss: ', ploss_hist[-1]
			print 'CCT-dot-true inverse covariance'
			#W=model.W.get_value()
			#b=np.exp(model.ln_b.get_value())
			#C=model.C.get_value()
			#cov_inv=np.dot(np.dot(C,C.T), np.dot(W.T, W)/(xvar**2))
			#print cov_inv
			#print model.weights_now.get_value()
			
		if ESS<npcl/2:
			resample()
			resample_counter=0
			r_hist.append(1)
		else:
			r_hist.append(0)
		
		s_hist.append(model.s_now.get_value())
		w_hist.append(model.weights_now.get_value())
		
		if math.isnan(ESS):
			print '\nSAMPLING ERROR===================\n'
			print 'Proposal loss: ', ploss_hist[-1]
			print 'CCT-dot-true inverse covariance'
			cov_inv=np.dot(np.dot(C,C.T), np.dot(W.T, W)/(xvar**2))
			print cov_inv
			break

W=model.W.get_value()
M=model.M.get_value()
b=np.exp(model.ln_b.get_value())
C=model.C.get_value()

f=open('W.cpl','wb')
cp.dump(W,f,2)
cp.dump(M,f,2)
cp.dump(b,f,2)
f.close()

#print spred.shape
#print spred
#print xpred.shape
#print xpred
#print hsmps.shape
#print hsmps

s_hist=np.asarray(s_hist)
w_hist=np.asarray(w_hist)
ess_hist=np.asarray(ess_hist)
s_av=np.mean(s_hist,axis=1)

u=s_av[1:,:]-np.dot(s_av[:-1,:],model.M.get_value())

pp.figure(1)
pp.matshow(M)

e_hist=np.asarray(e_hist)
l_hist=np.asarray(l_hist)-.5
r_hist=np.asarray(r_hist)-.5


#pp.figure(3)
#pp.plot(e_hist)
#pp.figure(4)
#pp.plot(s_av)
#pp.plot(r_hist, 'r')
#pp.plot(l_hist, 'k')

pp.figure(5)
pp.plot(ess_hist)

#pp.figure(6)
#pp.plot(u)

#pp.figure(7)
#pp.hist(u.flatten(),100)

#pp.figure(5)
#for i in range(npcl):
	#pp.scatter(range(len(s_hist)),s_hist[:,i,0],color=zip(w_hist[:,i],np.zeros(len(w_hist)),1.0-w_hist[:,i]))

#pp.figure(6)
#for i in range(npcl):
	#pp.scatter(range(len(s_hist)),s_hist[:,i,1],color=zip(w_hist[:,i],np.zeros(len(w_hist)),1.0-w_hist[:,i]))
	
#pp.figure(7)
#for i in range(npcl):
	#pp.scatter(range(len(s_hist)),s_hist[:,i,0],color=zip(np.ones(len(w_hist)),np.zeros(len(w_hist)),np.zeros(len(w_hist)),w_hist[:,i]))


#pp.figure(7)
#pp.plot(spred)


ploss_hist=np.asarray(ploss_hist)
pp.figure(9)
pp.plot(ploss_hist)

#pp.figure(6)
#for i in range(npcl):
	#pp.scatter(range(len(s_hist)),s_hist[:,i,0],c='k',s=5)

#pp.figure(5)
#for i in range(npcl):
	#pp.scatter(range(len(s_hist)),s_hist[:,i,1],color=zip(np.zeros(len(w_hist)),np.zeros(len(w_hist)),np.ones(len(w_hist)),w_hist[:,i]))


pp.show()

