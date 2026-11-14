% $Id: pst-tools.pro 249 2021-09-14 10:22:55Z herbert $
%
%% PostScript tools prologue for pstricks.tex.
%% Version 0.06, 2017/12/03
%%
%% This program can be redistributed and/or modified under the terms
%% of the LaTeX Project Public License Distributed from CTAN archives
%% in directory macros/latex/base/lppl.txt.
%
%
/Pi2 1.57079632679489661925640 def
/factorial { % n on stack, returns n! 
  dup 0 eq { 1 }{ 
    dup 1 gt { dup 1 sub factorial mul } if }
  ifelse } def 
%
/MoverN { % m n on stack, returns the binomial coefficient m over n
  2 dict begin
  /n exch def /m exch def
  n 0 eq { 1 }{
    m n eq { 1 }{
      m factorial n factorial m n sub factorial mul div } ifelse } ifelse 
  end
} def
%
/ps@ReverseOrderOfPoints { % on stack [P1 P2 P3 ...Pn]=>[Pn,Pn-1,...,P2,P1]
  5 dict begin       % all local
  aload length /n ED % number of coors
  n 2 div cvi /m ED  % number of Points
  /n1 n def
  m { n1 2 roll /n1 n1 2 sub def } repeat
  n array astore
  end
} def
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% subroutines for complex numbers, given as an array [a b] 
% which is a+bi = Real+i Imag
%
/cxadd {		% [a1 b1] [a2 b2] = [a1+a2 b1+b2]
  dup 0 get		% [a1 b1] [a2 b2] a2
  3 -1 roll		% [a2 b2] a2 [a1 b1]
  dup 0 get		% [a2 b2] a2 [a1 b1] a1
  3 -1 roll		% [a2 b2] [a1 b1] a1 a2
  add			% [a2 b2] [a1 b1] a1+a2
  3 1 roll		% a1+a2 [a2 b2] [a1 b1]
  1 get			% a1+a2 [a2 b2] b1
  exch 1 get		% a1+a2 b1 b2
  add 2 array astore
} def
%
/cxneg {		% [a b]
  dup 1 get		% [a b] b
  exch 0 get		% b a
  neg exch neg		% -a -b
  2 array astore
} def
%
/cxsub { cxneg cxadd } def  % same as negative addition
%
% [a1 b1][a2 b2] = [a1a2-b1b2 a1b2+b1a2] = [a3 b3]
/cxmul {		% [a1 b1] [a2 b2]
  dup 0 get		% [a1 b1] [a2 b2] a2
  exch 1 get		% [a1 b1] a2 b2
  3 -1 roll		% a2 b2 [a1 b1]
  dup 0 get		% a2 b2 [a1 b1] a1
  exch 1 get		% a2 b2 a1 b1
  dup			% a2 b2 a1 b1 b1
  5 -1 roll dup		% b2 a1 b1 b1 a2 a2
  3 1 roll mul		% b2 a1 b1 a2 b1a2
  5 -2 roll dup		% b1 a2 b1a2 b2 a1 a1
  3 -1 roll dup		% b1 a2 b1a2 a1 a1 b2 b2
  3 1 roll mul		% b1 a2 b1a2 a1 b2 a1b2
  4 -1 roll add		% b1 a2 a1 b2 b3
  4 2 roll mul		% b1 b2 b3 a1a2
  4 2 roll mul sub	% b3 a3
  exch 2 array astore
} def
%
% [a b]^2 = [a^2-b^2 2ab] = [a2 b2]
/cxsqr {		% [a b]   square root
  dup 0 get exch 1 get	% a b
  dup dup mul		% a b b^2
  3 -1 roll		% b b^2 a
  dup dup mul 		% b b^2 a a^2
  3 -1 roll sub		% b a a2
  3 1 roll mul 2 mul	% a2 b2	
  2 array astore
} def
%
/cxsqrt {		% [a b]
%  dup cxnorm sqrt /r exch def
%  cxarg 2 div RadtoDeg dup cos r mul exch sin r mul cxmake2 
  cxlog 		% log[a b]
  2 cxrdiv 		% log[a b]/2
  aload pop exch	% b a
  2.781 exch exp	% b exp(a)
  exch cxconv exch	% [Re +iIm] exp(a)
  cxrmul		%
} def
%
/cxarg { 		% [a b] 
  aload pop 		% a b
  exch atan 		% arctan b/a
  DegtoRad 		% arg(z)=atan(b/a)
} def
%
% log[a b] = [a^2-b^2 2ab] = [a2 b2]
/cxlog {		% [a b]
  dup 			% [a b][a b]
  cxnorm 		% [a b] |z|
  log 			% [a b] log|z|
  exch 			% log|z|[a b]
  cxarg 		% log|z| Theta
  cxmake2 		% [log|z| Theta]
} def
%
% square of magnitude of complex number
/cxnorm2 {		% [a b]
  dup 0 get exch 1 get	% a b
  dup mul			% a b^2
  exch dup mul add	% a^2+b^2
} def
%
/cxnorm {		% [a b]
  cxnorm2 sqrt
} def
%
/cxconj {		% conjugent complex
  dup 0 get exch 1 get	% a b
  neg 2 array astore	% [a -b]
} def
%
/cxre { 0 get } def	% real value
/cxim { 1 get } def	% imag value
%
% 1/[a b] = ([a -b]/(a^2+b^2)
/cxrecip {		% [a b]
  dup cxnorm2 exch	% n2 [a b]
  dup 0 get exch 1 get	% n2 a b
  3 -1 roll		% a b n2
  dup			% a b n2 n2
  4 -1 roll exch div	% b n2 a/n2
  3 1 roll div		% a/n2 b/n2
  neg 2 array astore
} def
%
/cxmake1 { 0 2 array astore } def % make a complex number, real given
/cxmake2 { 2 array astore } def	  % dito, both given
%
/cxdiv { cxrecip cxmul } def
%
% multiplikation by a real number
/cxrmul {		% [a b] r
  exch aload pop	% r a b
  3 -1 roll dup		% a b r r
  3 1 roll mul		% a r b*r
  3 1 roll mul		% b*r a*r
  exch 2 array astore   % [a*r b*r]
} def
%
% division by a real number
/cxrdiv {		% [a b] r
  1 exch div		% [a b] 1/r
  cxrmul
} def
%
% exp(i theta) = cos(theta)+i sin(theta) polar<->cartesian
/cxconv {		% theta
  RadtoDeg dup sin exch cos cxmake2
} def

%%%%% ### bubblesort ###
%% syntax : array bubblesort --> array2 trie par ordre croissant
%% code de Bill Casselman
%% http://www.math.ubc.ca/people/faculty/cass/graphics/text/www/
/bubblesort { % on stack must be an array [ ... ]
  4 dict begin
   /a exch def
   /n a length 1 sub def
   n 0 gt {
      % at this point only the n+1 items in the bottom of a remain to
      % the sorted largest item in that blocks is to be moved up into
      % position n
      n {
         0 1 n 1 sub {
            /i exch def
            a i get a i 1 add get gt {
               % if a[i] > a[i+1] swap a[i] and a[i+1]
               a i 1 add
               a i get
               a i a i 1 add get
               % set new a[i] = old a[i+1]
               put
               % set new a[i+1] = old a[i]
               put
            } if
         } for
         /n n 1 sub def
      } repeat
   } if
   a % return the sorted array
  end
} def
%
/concatstringarray{  %  [(a) (b) ... (z)] --> (ab...z)  20100422
  0 1 index { length add } forall 
  string     
  0 3 2 roll      
  { 3 copy putinterval length add }forall 
  pop  
} bind def
%
/concatstrings{ % (a) (b) -> (ab)  
  exch dup length    
  2 index length add string    
  dup dup 4 2 roll copy length
  4 -1 roll putinterval
} def
%
/reversestring { % (aBC) -> (CBa)
  5 dict begin
  /str exch def
  /L str length def
  /strTemp L string def
  /i 0 def
  L { 
    /I L 1 sub i sub def
    strTemp i str I 1 getinterval putinterval
    /i i 1 add def
  } repeat
  strTemp
  end
} def
%
/concatarray{ % [a c] [b d] -> [a c b d]  
  2 dict begin
  /a2 exch def
  /a1 exch def
  [ a1 aload pop a2 aload pop ]
  end
} def
%
/dot2comma {% on stack a string (...) 
  2 dict begin
  /Output exch def
  0 1 Output length 1 sub { 
    /Index exch def 
    Output Index get 46 eq { Output Index 44 put } if 
  } for
  Output
  end
} def
%
/rightTrim { % on stack the string and the character number to be stripped  
  1 dict begin
  /charNo exch def
  dup
  length 1 sub -1 0 { 
    /i exch def dup i get charNo ne { exit } if 
  } for
  0 i 1 add getinterval
  dup length string copy
  end
} bind def  % leaves the stripped string on the stack

/psStringwidth /stringwidth load def
/psShow /show load def

%/stringwidth{ 32 rightTrim psStringwidth } bind def

%/show { 32 rightTrim psShow } bind def
%-----------------------------------------------------------------------------%

/pgffunctions {
    /pgfsc{}bind def% stroke color is empty by default
    /pgffc{}bind def% fill color is empty by default
    /pgfstr{stroke}bind def%
    /pgffill{fill}bind def%
    /pgfeofill{eofill}bind def%
    /pgfe{a dup 0 rlineto exch 0 exch rlineto neg 0 rlineto closepath}bind def% rectangle
    /pgfw{setlinewidth}bind def% setlinewidth
    /pgfs{save pgfpd 72 Resolution div 72 VResolution div neg scale 
      magscale{1 DVImag div dup scale}if 
      pgfx neg pgfy neg translate pgffoa .setopacityalpha}bind def% save
    /pgfr{pgfsd restore}bind def %restore
    userdict begin%
    /pgfo{pgfsd /pgfx currentpoint /pgfy exch def def @beginspecial}bind def %open
    /pgfc{newpath @endspecial pgfpd}bind def %close
    /pgfsd{globaldict /pgfdelta /delta where {pop delta} {0} ifelse put}bind def% save delta
    /pgfpd{/delta globaldict /pgfdelta get def}bind def % put delta
    /.setopacityalpha where {pop} {/.setopacityalpha{pop}def} ifelse % install .setopacityalpha 
    /.pgfsetfillopacityalpha{/pgffoa exch def
      /pgffill{gsave pgffoa .setopacityalpha fill 1 .setopacityalpha newpath fill grestore newpath}bind def
      /pgfeofill{gsave pgffoa .setopacityalpha eofill 1 .setopacityalpha newpath eofill grestore newpath}bind def}bind def
    /.pgfsetstrokeopacityalpha{/pgfsoa exch def /pgfstr{gsave pgfsoa .setopacityalpha stroke grestore newpath}bind def}bind def
    /pgffoa 1 def
    /pgfsoa 1 def
    end
} def
%-----------------------------------------------------------------------------%
% END pst-tools.pro
