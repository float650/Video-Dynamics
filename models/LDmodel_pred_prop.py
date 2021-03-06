import numpy as np
from matplotlib import pyplot as pp

import scipy.linalg as spla

import math

import theano
import theano.tensor as T

from theano.sandbox.rng_mrg import MRG_RandomStreams as RandomStreams
#from theano.tensor.shared_randomstreams import RandomStreams

class LDmodel():
	
	'''
	Models discreet-time continuous data as a linear transformation
	of a linear dynamical system with sparse "noise".
	
	x: data
	s: latent variable
	u: sparse noise
	n: gaussian noise
	W: generative matrix
	M: dynamical matrix
	
	s_(t+1) = M*s_t + u
	x_t = W*s_t + n
	
	In this version the proposal distribution is just the predictive
	part, not the generative part.
	
	'''
	
	
	def __init__(self, nx, ns, npcl, nsamps, xvar=1.0, init_W=None):
		
		#generative matrix
		if init_W==None:
			init_W=np.asarray(np.random.randn(nx,ns)/0.1,dtype='float32')
		
		#normalize the columns of W to be unit length
		#(maybe unnecessary if sampling?)
		init_W=init_W/np.sqrt(np.sum(init_W**2,axis=0))
		
		#dynamical matrix
		init_M=np.asarray(np.eye(ns),dtype='float32')
		
		#sparsity parameters
		#parametrized as the exponent of ln_b to ensure positivity
		init_ln_b=np.asarray(-1.0*np.ones(ns),dtype='float32')
		
		self.W=theano.shared(init_W)
		self.M=theano.shared(init_M)
		self.ln_b=theano.shared(init_ln_b)
		
		#for ease of use
		self.b=T.exp(self.ln_b)
		self.br=T.reshape(self.b,(ns,1))
		
		init_s_now=np.asarray(np.zeros((npcl,ns)),dtype='float32')
		init_weights_now=np.asarray(np.ones(npcl)/float(npcl),dtype='float32')
		
		init_s_past=np.asarray(np.zeros((npcl,ns)),dtype='float32')
		init_weights_past=np.asarray(np.ones(npcl)/float(npcl),dtype='float32')
		
		self.s_now=theano.shared(init_s_now)
		self.weights_now=theano.shared(init_weights_now)
		
		self.s_past=theano.shared(init_s_past)
		self.weights_past=theano.shared(init_weights_past)
		
		self.xvar=np.asarray(xvar,dtype='float32')
		
		self.nx=nx		#dimensionality of observed variables
		self.ns=ns		#dimensionality of latent variables
		self.npcl=npcl	#numer of particles in particle filter
		self.nsamps=nsamps  #number of samples to draw from the joint during learning
		
		#this is used to convert binary index vectors to scalar indices
		idx_vec=np.arange(npcl)
		self.idx_vec=theano.shared(idx_vec)
		
		self.theano_rng = RandomStreams()
		
		self.init_multi_samp=theano.shared(np.asarray(np.arange(npcl),dtype='int64'))
		self.idx_helper=theano.shared(np.asarray(np.arange(npcl),dtype='int64'))
		
		self.params=							[self.W, self.M, self.ln_b]
		self.rel_lrates=theano.shared(np.asarray([  10.0,    10.0,     2000.0]   ,dtype='float32'))
	
	
	def sample_proposal_s(self):
		
		#s is npcl-by-ns
		
		u=self.theano_rng.uniform(size=T.shape(self.s_now))-0.5
		
		mean_term=self.get_prediction(self.s_now)
		
		s_prop=mean_term-T.sgn(u)*T.log(1.0-2.0*T.abs_(u))*self.b
		
		#return T.cast(s_prop,'float32'), T.cast(s_pred,'float32'), T.cast(prop_term,'float32'), prop_mean
		return s_prop
	
	
	def forward_filter_step(self, xp):
		
		#need to sample from the proposal distribution first
		s_samps = self.sample_proposal_s()
		
		updates={}
		
		#now that we have samples from the proposal distribution, we need to reweight them
		
		recons=T.dot(self.W, s_samps.T)
		
		x_terms=-T.sum((recons-T.reshape(xp,(self.nx,1)))**2,axis=0)/(2.0*self.xvar**2)
		
		energies=x_terms#-T.sum(T.abs_(s_samps),axis=1)
		
		#to avoid exponentiating large or very small numbers, I 
		#"re-center" the reweighting factors by adding a constant, 
		#as this has no impact on the resulting new weights
		
		energies_recentered=energies-T.max(energies)
		
		alpha=T.exp(energies_recentered) #these are the reweighting factors
		
		new_weights_unnorm=self.weights_now*alpha
		normalizer=T.sum(new_weights_unnorm)
		new_weights=new_weights_unnorm/normalizer  #need to normalize new weights
		
		updates[self.s_past]=T.cast(self.s_now,'float32')
		
		updates[self.s_now]=T.cast(s_samps,'float32')
		
		updates[self.weights_past]=T.cast(self.weights_now,'float32')
		updates[self.weights_now]=T.cast(new_weights,'float32')
		
		#return normalizer, energies_recentered, s_samps, s_pred, T.dot(self.W.T,(xp-self.c)), updates
		#return normalizer, energies_recentered, updates
		#return h_samps, updates
		return updates
	
	
	def get_prediction(self, s):
		
		s_pred=T.dot(s, self.M)
		
		return s_pred
	
	
	def update_params(self, x1, x2, lrate):
		
		#this function samples from the joint posterior and performs
		# a step of gradient ascent on the log-likelihood
		
		sp=self.get_prediction(self.s_past)
		
		sp_big=T.reshape(T.extra_ops.repeat(sp,self.nsamps,axis=1).T,(self.ns, self.npcl*self.nsamps))
		
		#s2_idxs=self.sample_multinomial_vec(self.weights_now,4)
		bsamp=self.theano_rng.multinomial(pvals=T.extra_ops.repeat(T.reshape(self.weights_now,(1,self.npcl)),self.nsamps,axis=0))
		s2_idxs=T.dot(self.idx_vec,bsamp.T)
		
		s2_samps=self.s_now[s2_idxs] #ns by nsamps
		
		s2_big=T.extra_ops.repeat(s2_samps,self.npcl,axis=0).T #ns by npcl*nsamps
		
		diffs=T.sum(T.abs_(sp_big-s2_big)/self.br,axis=0)
		#diffs=T.sum(T.abs_(sp_big-s2_big),axis=0)
		probs_unnorm=self.weights_past*T.exp(-T.reshape(diffs,(self.nsamps,self.npcl)))
		
		#s1_idxs=self.sample_multinomial_mat(probs_unnorm,4)
		s1_idxs=T.dot(self.idx_vec,self.theano_rng.multinomial(pvals=probs_unnorm).T)
		s1_samps=self.s_past[s1_idxs]
		
		x2_recons=T.dot(self.W, s2_samps.T)
		
		s_pred = self.get_prediction(s1_samps)
		
		sterm=-T.mean(T.sum(T.abs_((s2_samps-s_pred)/self.b),axis=1)) - T.sum(T.log(self.b))
		
		#xterm1=-T.mean(T.sum((x1_recons-T.reshape(x1,(self.nx,1)))**2,axis=0)/(2.0*self.xvar**2))
		xterm2=-T.mean(T.sum((x2_recons-T.reshape(x2,(self.nx,1)))**2,axis=0)/(2.0*self.xvar**2))
		
		
		energy = xterm2 + sterm 
		
		learning_params=[self.params[i] for i in range(len(self.params)) if self.rel_lrates[i]!=0.0]
		learning_rel_lrates=[self.rel_lrates[i] for i in range(len(self.params)) if self.rel_lrates[i]!=0.0]
		gparams=T.grad(energy, learning_params, consider_constant=[s1_samps, s2_samps])
		
		updates={}
		
		# constructs the update dictionary
		for gparam, param, rel_lr in zip(gparams, learning_params, learning_rel_lrates):
			#gnat=T.dot(param, T.dot(param.T,param))
			if param==self.M:
				#I do this so the derivative of M doesn't depend on the sparsity parameters
				updates[param] = T.cast(param + gparam*T.reshape(self.b,(1,self.ns))*lrate*rel_lr,'float32')
				#updates[param] = T.cast(param + gparam*lrate*rel_lr,'float32')
			elif param==self.b:
				updates[param] = T.cast(param + gparam*T.reshape(1.0/self.b,(1,self.ns))*lrate*rel_lr,'float32')
			else:
				updates[param] = T.cast(param + gparam*lrate*rel_lr,'float32')
		
		newW=updates[self.W]
		updates[self.W]=newW/T.sqrt(T.sum(newW**2,axis=0))
		
		return energy, updates
		
	
	def get_ESS(self):
		
		return 1.0/T.sum(self.weights_now**2)
	
	
	def resample(self):
		
		updates={}
		#samp=self.theano_rng.multinomial(pvals=self.weights_now)
		#idxs=self.sample_multinomial_vec(self.weights_now,3)
		samp=self.theano_rng.multinomial(pvals=T.extra_ops.repeat(T.reshape(self.weights_now,(1,self.npcl)),self.npcl,axis=0))
		idxs=T.dot(self.idx_vec,samp.T)
		s_samps=self.s_now[idxs]
		updates[self.s_now]=s_samps
		updates[self.weights_now]=T.cast(T.ones_like(self.weights_now)/T.cast(self.npcl,'float32'),'float32') #dtype paranoia
		
		return updates
	
	
	def simulate_step(self, s):
		
		s=T.reshape(s,(1,self.ns))
		
		sp=self.get_prediction(s)
		
		xp=T.dot(self.W, sp.T)
		
		return T.cast(sp,'float32'), T.cast(xp,'float32')
		
	
	def simulate_forward(self, n_steps):
		
		
		s0=T.sum(self.s_now*T.reshape(self.weights_now,(self.npcl,1)),axis=0)
		s0=T.reshape(s0,(1,self.ns))
		[sp, xp], updates = theano.scan(fn=self.simulate_step,
										outputs_info=[s0, None],
										n_steps=n_steps)
		
		return sp, xp, updates
	

	#def multinomial_step_vec(self,samp,weights):
		
		#u=self.theano_rng.uniform(size=self.weights_now.shape)
		#i=self.theano_rng.random_integers(size=self.weights_now.shape, low=0, high=self.npcl-1)
		#Wnow=weights[samp]
		#Wstep=weights[i]
		#probs=Wstep/Wnow
		#out=T.switch(u<probs, i, samp)
		#return out
	
	
	#def sample_multinomial_vec(self,weights,nsteps):
		
		##this function samples from a multinomial distribution using
		##the Metropolis method as in [Murray, Lee, Jacob 2013]
		##weights are unnormalized
		##this is biased for small nsteps, but could be faster than the
		##native theano multinomial sampler and the use of unnormalized
		##weights improves numerical stability
		
		##in this version 'weights' is assumed to be a vector, so that
		##the same distribution is sampled len(weights) times
		#samp0=self.init_multi_samp
		#samps, updates = theano.scan(fn=self.multinomial_step_vec,
										#outputs_info=[samp0],
										#non_sequences=[weights],
										#n_steps=nsteps)
		
		#return samps[-1]
	
	
	#def multinomial_step_mat(self,samp,weights):
		
		#u=self.theano_rng.uniform(size=self.weights_now.shape)
		#i=self.theano_rng.random_integers(size=self.weights_now.shape, low=0, high=self.npcl-1)
		#Wnow=weights[self.idx_helper,samp]
		#Wstep=weights[self.idx_helper,i]
		#probs=Wstep/Wnow
		#out=T.switch(u<probs, i, samp)
		#return out
	
	
	#def sample_multinomial_mat(self,weights,nsteps):
		
		##this function samples from a multinomial distribution using
		##the Metropolis method as in [Murray, Lee, Jacob 2013]
		##weights are unnormalized
		##this is biased for small nsteps, but could be faster than the
		##native theano multinomial sampler and the use of unnormalized
		##weights improves numerical stability
		
		##in this version 'weights' is a matrix, so that we get samples
		##from different distributions
		#samp0=self.init_multi_samp
		#samps, updates = theano.scan(fn=self.multinomial_step_mat,
										#outputs_info=[samp0],
										#non_sequences=[weights],
										#n_steps=nsteps)
		
		#return samps[-1]

	
	def set_rel_lrates(self, new_rel_lrates):
		updates={}
		updates[self.rel_lrates]=new_rel_lrates
		return updates


