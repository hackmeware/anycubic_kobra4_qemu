// SPDX-License-Identifier: MIT
using System;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.AT32;
namespace Antmicro.Renode.Peripherals.AT32Tests
{
 public class GenericElectromechanicalTests : IPeripheral
 {
  public void Reset(){}
  private int n;
  private void Check(bool ok,string label){if(!ok)throw new Exception(label);n++;}
  private void Near(double a,double b,double eps,string label){Check(Math.Abs(a-b)<=eps,label+": "+a+" vs "+b);}
  public string Run()
  {
   n=0;
   var a=new GenericStepperRotor();a.Advance(0,0,0.01);
   Near(a.StoredEnergy,0,0,"no excitation no energy");Near(a.AngleRadians,0,0,"no spontaneous motion");
   a.SetInitialState(0.3,-0.7,0.023,12);
   Near(a.CurrentA*a.BackEmfA+a.CurrentB*a.BackEmfB,a.ElectromagneticTorque*a.VelocityRadiansPerSecond,1e-12,"reciprocal power");
   var torque=new GenericStepperRotor(inertia:0.001,fluxLinkage:0,damping:0,loadTorque:-0.001);
   torque.Advance(0,0,0.1);Near(torque.VelocityRadiansPerSecond,0.1,1e-9,"constant external torque acceleration");Near(torque.AngleRadians,0.005,1e-9,"constant torque displacement");
   var decay=new GenericStepperRotor();decay.LockedRotor=true;decay.SetInitialState(1,-2,0,0);decay.Advance(0,0,0.0015);
   Near(decay.CurrentA,Math.Exp(-1),1e-12,"disabled A decay");Near(decay.CurrentB,-2*Math.Exp(-1),1e-12,"disabled B decay");
   var drive=new GenericStepperRotor(damping:0);drive.LockedRotor=true;drive.Advance(0,2,0.02);
   Check(drive.ElectromagneticTorque>0.099,"locked winding torque");Near(drive.AngleRadians,0,0,"actual rotor lock");Near(drive.ConstraintReactionTorque,-drive.ElectromagneticTorque,1e-12,"lock reaction");
   var free=new GenericStepperRotor();free.Advance(0,2,0.005);Check(free.AngleRadians>0,"physical excitation moves free rotor");Check(Math.Abs(free.CurrentB-drive.CurrentB)>0.001,"motion changes current through EMF");
   var contact=new GenericStepperRotor(fluxLinkage:0,damping:0.001);contact.ConfigureContact(-0.01,0.01,10,0.01);contact.SetInitialState(0,0,0,5);
   double initial=contact.StoredEnergy;contact.Advance(0,0,0.05);Check(contact.StoredEnergy<=initial+1e-7,"passive contact dissipates energy");Check(Math.Abs(contact.AngleRadians)<0.02,"contact reaction limits motion");
   contact.SetInitialState(0,0,0.02,1);Check(contact.ContactReactionTorque<0,"upper contact pushes inward");contact.SetInitialState(0,0,-0.02,-1);Check(contact.ContactReactionTorque>0,"lower contact pushes inward");
   var passive=new GenericStepperRotor();passive.SetInitialState(1,0,0.01,3);initial=passive.StoredEnergy;passive.Advance(0,0,0.01);Check(passive.StoredEnergy<initial,"zero-supply energy decreases");
   var opening=new GenericStepperRotor();opening.SetInitialState(1,1,0,0);opening.OpenWinding=true;opening.Advance(24,24,0.01);Near(opening.CurrentA,0,0,"open winding A");Near(opening.CurrentB,0,0,"open winding B");Near(opening.DissipatedByIdealOpening,0.003,1e-12,"opening energy accounted");
   bool threw=false;try{new GenericStepperRotor(inertia:0);}catch(ArgumentException){threw=true;}Check(threw,"zero inertia rejected");
   threw=false;try{passive.Advance(double.NaN,0,1);}catch(ArgumentException){threw=true;}Check(threw,"NaN rejected");
   threw=false;try{passive.ConfigureContact(1,-1);}catch(ArgumentException){threw=true;}Check(threw,"invalid contact bounds rejected");
   Check(!Double.IsInfinity(free.StoredEnergy)&&!Double.IsNaN(free.StoredEnergy),"finite dynamics");
   return "ELECTROMECHANICAL EQUATION TESTS PASS: "+n;
  }
 }
}
