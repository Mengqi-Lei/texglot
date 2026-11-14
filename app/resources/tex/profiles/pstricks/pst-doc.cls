% $Id: pst-doc.cls 1044 2019-04-11 09:32:09Z herbert $
%
%%
%% The PSTricks Project
%%
%% ``pst-doc'' class for use with the PSTricks documentation.
%%
%% Copyright (C) 2009-2017 Herbert Voss
%%
%% It may be distributed and/or modified under the conditions
%% of the LaTeX Project Public License, either version 1.3
%% of this license or (at your option) any later version.
%%
%% See http://www.latex-project.org/lppl.txt for details.
%%
%
\listfiles
\ProvidesClass{pst-doc}[2017/04/18 v 0.20 PSTricks documentation class (hv)]
\DeclareOption*{\PassOptionsToClass{\CurrentOption}{scrartcl}}
\ProcessOptions\relax
%
\LoadClass{scrartcl}
%
\RequirePackage[dvipsnames,x11names,svgnames,table]{xcolor}
\RequirePackage{iftex}
\RequirePackage{everyshi}
\RequirePackage{amsmath, amssymb} 
\iftutex
  \usepackage{unicode-math}
  \usepackage{libertinus-otf}
  \setmonofont[Scale=MatchLowercase,FakeStretch=0.92]{DejaVu Sans Mono}
%  \setmathfont{XITS Math}
\else
  \RequirePackage[T1]{fontenc}
  \RequirePackage{textcomp}
  %\RequirePackage[euler-digits]{eulervm}
  \RequirePackage{bera}
  %\RequirePackage[scaled=0.85]{luximono}
\fi
\usepackage[includeheadfoot,lmargin=2cm,tmargin=1cm,bmargin=1.5cm,rmargin=1.5cm]{geometry}
\RequirePackage{ifpdf}
% Define commands that don't eat spaces.
\RequirePackage{xspace}
\makeatletter
\providecommand{\IfPackageLoaded}[2]{\@ifpackageloaded{#1}{#2}{}}
\providecommand{\IfPackageNotLoaded}[2]{\@ifpackageloaded{#1}{}{#2}}
\providecommand{\IfElsePackageLoaded}[3]{\@ifpackageloaded{#1}{#2}{#3}}
\providecommand{\IfChapterDefined}[1]{\ifthenelse{\boolean{chapteravailable}}{#1}{}}%
\providecommand{\IfElseChapterDefined}[2]{\ifthenelse{\boolean{chapteravailable}}{#1}{#2}}%
\providecommand{\IfDefined}[2]{\ifcsname #1\endcsname #2 \fi}
\providecommand{\IfElseDefined}[3]{\ifcsname #1\endcsname #2 \else #3 \fi}
\providecommand{\IfElseUnDefined}[3]{\ifcsname #1\endcsname #3 \else #2\fi}
% Definde frontmatter, mainmatter and backmatter if not defined
\@ifundefined{frontmatter}{%
   \newcommand{\frontmatter}{%
      %In Roemischen Buchstaben nummerieren (i, ii, iii)
      \pagenumbering{roman}}
}{}
\@ifundefined{mainmatter}{%
   % scrpage benoetigt den folgenden switch
   % wenn \mainmatter definiert ist.
   \newif\if@mainmatter\@mainmattertrue
   \newcommand{\mainmatter}{%
      % -- Seitennummerierung auf Arabische Zahlen zuruecksetzen (1,2,3)
      \pagenumbering{arabic}%
      \setcounter{page}{1}}
}{}
\@ifundefined{backmatter}{%
   \newcommand{\backmatter}{
      %In Roemischen Buchstaben nummerieren (i, ii, iii)
      \pagenumbering{roman}}
}{}

% Pakete speichern die spaeter geladen werden sollen
\newcommand{\LoadPackagesNow}{}
\newcommand{\LoadPackageLater}[1]{%
   \g@addto@macro{\LoadPackagesNow}{%
      \RequirePackage{#1}%
   }%
}
%
\RequirePackage{makeidx}
\makeindex
\RequirePackage{calc}
\RequirePackage{babel}
\RequirePackage{xkeyval}
\RequirePackage{pst-xkey}
\RequirePackage{pstricks}
\RequirePackage{xkvview}
%\let\pstricksFV\fileversion
%\let\pstricksFD\filedate
\RequirePackage{multido}
\RequirePackage{lscape}
\RequirePackage{graphicx}
\RequirePackage{eso-pic}
\definecolor{DOrange}{rgb}{1,.4,.2}
\RequirePackage{tabularx,ragged2e}
\RequirePackage{booktabs}
\RequirePackage[bottom,stable,ragged]{footmisc}
%\RequirePackage{chngcntr}
\RequirePackage{nameref}
\RequirePackage{varioref} 
\RequirePackage{subfig} 
\RequirePackage{setspace}
\RequirePackage{paralist}
\RequirePackage{biblatex}
%
\RequirePackage{fancyvrb} 
\newenvironment{Xverbatim}[2][]%
  {\VerbatimEnvironment
\handle@index{#2}
\begin{Verbatim}[#1]}
{\end{Verbatim}}
\newcommand\use@index@vals{\index@vals\global\let\index@vals\relax}
\def\handle@index#1{%
    \gdef\index@vals{#1}%
    \def\FancyVerbFormatLine##1{\FV@ObeyTabs{##1}\use@index@vals}}

%\singlespace 
\RequirePackage{showexpl}
\renewcommand*\SX@Info{}%
\definecolor{hellgelb}{rgb}{1,1,0.85}
\definecolor{colKeys}{rgb}{0,0,1}
\definecolor{colIdentifier}{rgb}{0,0,0}
\definecolor{colComments}{rgb}{1,0,0}
\definecolor{colString}{rgb}{0,0.5,0}
\providecommand\ON{%
  \gdef\lst@alloverstyle##1{%
    \fboxrule=0pt
    \fboxsep=0pt
    \fcolorbox{Black!15}{Black!15}{\bfseries\strut##1}%
}}
\providecommand\OFF{\xdef\lst@alloverstyle##1{##1}}
\lstset{%
    language=PSTricks,%
    float=hbp,%
    basicstyle=\ttfamily\small, %
    identifierstyle=\color{colIdentifier}, %
    keywordstyle=\color{colKeys}, %
    stringstyle=\color{colString}, %
    commentstyle=\color{colComments}, %
    columns=flexible, %
    tabsize=4, %
    frame=single, %
    extendedchars=true, %
    showspaces=false, %
    showstringspaces=false, %
%    numbers=left, 
%    numbersep=0.8em,
%    numberstyle=\tiny, %
    breaklines=true, %
    breakautoindent=true, 
    captionpos=b,
    xleftmargin=1em
}
\lstset{explpreset={pos=t,wide=false,rframe={},preset=\centering}}
\lstdefinestyle{syntax}{backgroundcolor=\color{blue!15},numbers=none,xleftmargin=0pt,xrightmargin=0pt,
    frame=single}
\lstdefinestyle{code}{backgroundcolor=\color{red!15},%numbers=left,
xleftmargin=0pt,xrightmargin=0pt,
    frame=single}
%
\usepackage{manfnt}
\newcommand\XInfofont{\color{blue}\fontsize{8pt}{10pt}\normalfont\itshape}
\newcommand\XInfo[2][1]{\marginpar
  [\XInfocorr{#1}\raggedleft\XInfofont#2]%
  {\XInfocorr{#1}\raggedright\XInfofont#2}}
\newcommand\XInfocorr[1]{\mbox{}\par
  \ifcase#1\relax
    \vspace{-10pt}\or
    \vspace{2pt}\or
    \vspace{14pt}\else
    \ifnum #1=-1  \vspace{-22pt}\else\ERROR\fi
  \fi}
\newcommand\XInfoDanger[2][1]{\marginpar
  [\XInfocorr{#1}\raggedleft\XInfofont
   \let\\\@normalcr
   \hangafter-2\hangindent=-.9pc\parindent=-\@flushglue
   \noindent\rlap{\makebox[\marginparwidth]{\hfill\lower1.2pt\hbox{\dbend}\hspace*{-8pt}}}\hfill#2]%
  {\XInfocorr{#1}\raggedright\XInfofont
   \let\\\@normalcr
   \hangafter-2\hangindent=.9pc\noindent\llap{\lower1.2pt\hbox{\lhdbend}\,}#2}}
%
\RequirePackage{xkvview}
\raggedbottom 
\definecolor{sectioncolor}{RGB}{0, 0, 255}    % Schwarz
\definecolor{textcolor}{RGB}{0, 0, 0}        % Schwarz
\definecolor{shadecolor}{gray}{0.90}
\colorlet{pdflinkcolor}{DOrange}
\colorlet{pdfurlcolor}{DOrange}
\colorlet{pdffilecolor}{DOrange}
\colorlet{stringcolor}{green!40!black!100}
\colorlet{commencolor}{blue!0!black!100}
\RequirePackage[automark]{scrlayer-scrpage}

\pagestyle{scrheadings} 
\clearscrheadings
\clearscrplain
\ohead{\pagemark}
\ihead{\headmark}
\ofoot[\pagemark]{} 
\automark[subsection]{section}
\setheadsepline{.4pt}[\color{DOrange}]
\setheadwidth[0pt]{text}
\setfootwidth[0pt]{text}
%% Fussnoten =============================================================
% Keine hochgestellten Ziffern in der Fussnote (KOMA-Script-spezifisch):
\deffootnote{1.5em}{1em}{\makebox[1.5em][l]{\thefootnotemark}}
\addtolength{\skip\footins}{\baselineskip} % Abstand Text <-> Fussnote
%% Schriften (Sections )==================================================
\newcommand\SectionFontStyle{\sffamily}
\setkomafont{sectioning}{\bfseries\SectionFontStyle} %  % Titelzeilen % \bfseries
\setkomafont{pagenumber}{\bfseries\SectionFontStyle}             % Seitenzahl
\setkomafont{pagehead}{\small\sffamily}        % Kopfzeile
%\setkomafont{pagefoot}{\small\sffamily}        % Kopfzeile
\setkomafont{descriptionlabel}{\itshape}        % Kopfzeile
\addtokomafont{sectioning}{\color{sectioncolor}} % Farbe der Ueberschriften
\renewcommand*{\raggedsection}{\raggedright} % Titelzeile linksbuendig, haengend
\RequirePackage{caption}
\captionsetup{
   margin = 10pt,
   font = {small,rm},
   labelfont = {small,bf},
   format = plain, % oder 'hang'
   indention = 0em,  % Einruecken der Beschriftung
   labelsep = colon, %period, space, quad, newline
   justification = RaggedRight, % justified, centering
   singlelinecheck = true, % false (true=bei einer Zeile immer zentrieren)
   position = bottom %top
}
%%% Bugfix Workaround
\DeclareCaptionOption{parskip}[]{}
\DeclareCaptionOption{parindent}[]{}

% Aussehen der Captions fuer subfigures (subfig-Paket)
\IfPackageLoaded{subfig}{
 \captionsetup[subfloat]{%
   margin = 10pt,
   font = {small,rm},
   labelfont = {small,bf},
   format = plain, % oder 'hang'
   indention = 0em,  % Einruecken der Beschriftung
   labelsep = space, %period, space, quad, newline
   justification = RaggedRight, % justified, centering
   singlelinecheck = true, % false (true=bei einer Zeile immer zentrieren)
   position = bottom, %top
   labelformat = parens % simple, empty % Wie die Bezeichnung gesetzt wird
 }
}
\setcounter{secnumdepth}{2}    % Abbildungsnummerierung mit groesserer Tiefe
\setcounter{tocdepth}{2}		 % Inhaltsverzeichnis mit groesserer Tiefe
%
% Inhalte von List of Figures
\IfPackageLoaded{subfig}{\setcounter{lofdepth}{1}  %1 = nur figures, 2 = figures + subfigures
}
\RequirePackage{xurl}
\RequirePackage[colorlinks,
   urlcolor=pdfurlcolor,    
   filecolor=pdffilecolor,  
   linkcolor=pdflinkcolor,
   breaklinks,        
   linktocpage=true]{hyperref}
%\ifxetex
%\else
%  \RequirePackage{breakurl}
%\fi
\newsavebox\TBox
\newenvironment{Bsp}[1]{%
  \par\bigskip%
  \begin{lrbox}{\TBox}
  \begin{minipage}{\linewidth-2\fboxrule}%
    \setlength\fboxsep{1mm}%
    \colorbox{DOrange}{\parbox{\linewidth-2\fboxsep}{%
      \color{White}\sffamily#1}}\par
    \fontsize{10}{12pt}\fontshape{it}\selectfont%
    \begin{quote}
}{%
\par\bigskip\end{quote}\end{minipage}\end{lrbox}\fboxsep=0pt%
    \fcolorbox{DOrange}{White}{\usebox\TBox}\par\bigskip}
    
\newcommand{\RDO}{\color{DOrange!25}\rule[-1mm]{10mm}{5mm}}

\DeclareRobustCommand\PST{\texttt{PSTricks\xspace}}
\DeclareRobustCommand\PS{\texttt{PostScript\xspace}}
\def\dt{\ensuremath{\,\mathrm{d}t}}
\def\Index#1{\index{#1}#1}
%
\def\LPack#1{\texttt{#1}\index{#1@\texttt{#1}}\index{Package!#1@\texttt{#1}}}
\def\nxLPack#1{\texttt{#1}}
\def\Lprog#1{\texttt{#1}\index{#1@\texttt{#1}}\index{Program!#1@\texttt{#1}}}
\let\nxLprog\nxLPack
\def\LFile#1{\texttt{#1}\index{#1@\texttt{#1}}\index{File!#1@\texttt{#1}}}
\def\nxLFile#1{\texttt{#1}}
\def\Lext#1{\texttt{.#1}\index{#1@\texttt{.#1}}\index{Extension!#1@\texttt{.#1}}}
\def\nxLext#1{\texttt{.#1}}
\def\xLcs#1{\index{#1@\nxLcs{#1}}\index{Macro!#1@\nxLcs{#1}}}
\def\Lcs#1{\nxLcs{#1}\xLcs{#1}}
\def\LcsStar#1{\index{#1*@\nxLcs{#1*}}\index{Macro!#1@\nxLcs{#1*}}\nxLcs{#1}\OptArg*{*}}
\def\nxLcs#1{\texttt{\textbackslash#1}}
\def\xLenv#1{\index{#1@\texttt{#1}}\index{Environment!#1@\texttt{#1}}}
\def\Lenv#1{\texttt{#1}\xLenv{#1}}
\def\Ldim#1{\texttt{\textbackslash#1}\index{#1@\texttt{\textbackslash#1}}\index{Dimension!#1@\texttt{\textbackslash#1}}}
\def\Lskip#1{\texttt{\textbackslash#1}\index{#1@\texttt{\textbackslash#1}}\index{Skip!#1@\texttt{\textbackslash#1}}}
\def\Lkeyword#1{\texttt{#1}\xLkeyword{#1}}
\def\xLkeyword#1{\index{#1@\texttt{#1}}\index{Keyword!#1@\texttt{#1}}}
\def\nxLkeyword#1{\texttt{#1}}

\def\LKeyword#1{\LKeyword@i#1!!}
\def\LKeyword@i#1=#2!!{\Lkeyword{#1}\nxLkeyword{=#2}}
\let\nxLKeyword\nxLenv % same formatting

\let\nxLkeyval\nxLkeyword
\let\nxLenv\nxLkeyword
\let\nxLps\nxLkeyword
\def\LColor#1{\texttt{#1}\xLColor{#1}}
\def\xLColor#1{\index{#1@\texttt{#1}}\index{Color!#1@\texttt{#1}}}
\def\Lkeyval#1{\texttt{#1}\xLkeyval{#1}}
\def\xLkeyval#1{\index{#1@\texttt{#1}}\index{Keyvalue!#1@\texttt{#1}}}
\def\xLoption#1{\index{#1@\texttt{#1}}\index{Package option!#1@\texttt{#1}}}
\def\Loption#1{\texttt{#1}\xLoption{#1}}
\def\LPS#1{\texttt{#1}\index{#1@\texttt{#1}}\index{PostScript!#1@\texttt{#1}}}
\def\xLps#1{\index{#1@\texttt{#1}}\index{PostScript!#1@\texttt{#1}}}
\def\nxLps#1{\texttt{#1}}
\def\Lps#1{\nxLps{#1}\xLps{#1}}
\def\LClass#1{\texttt{#1}\index{#1@\texttt{#1}}\index{Class!#1@\texttt{#1}}}
\let\nxLClass\nxLPack
\let\nxLdim\nxLcs
\let\nxLskip\nxLcs
\def\Lctr#1{\texttt{#1}\index{#1@\texttt{#1}}\index{Counter!#1@\texttt{#1}}}
\def\LCtr#1{\texttt{#1}\index{#1@\texttt{#1}}\index{TeX Counter@\TeX\ Counter!#1@\texttt{#1}}}
\def\nxLctr#1{\texttt{#1}}
%
\newcommand\Lnotation [1]{\nxLnotation{#1}\xLnotation{#1}}
\newcommand\Lmnotation[1]{\nxLnotation{#1}\xLmnotation{#1}}
\newcommand\xLnotation[1]{\index{Syntax!#1@\nxLnotation{#1}}\index{#1@\nxLnotation{#1}}}
\def\nxLnotation#1{\texttt{#1}}
\def\xLkeyset#1{\expandafter\xLkeyset@i#1\@nil}
\def\xLkeyset@i#1=#2\@nil{\index{#1@\texttt{#1}}\index{Keyword!#1@\texttt{#1}}
  \index{#2@\texttt{#2}}\index{Value!#2@\texttt{#2}}}
\def\Lkeyset#1{\expandafter\Lkeyset@i#1\@nil}
\def\Lkeyset@i#1=#2\@nil{\texttt{#1=#2}%
  \index{#1@\texttt{#1}}\index{Keyword!#1@\texttt{#1}}
  \index{#2@\texttt{#2}}\index{Value!#2@\texttt{#2}}}
%
\def\xLKeyset#1{\expandafter\xLKeyset@i#1\@nil}% without using the right value of =
\def\xLKeyset@i#1=#2\@nil{\index{#1@\texttt{#1}}\index{Keyword!#1@\texttt{#1}}}
\def\LKeyset#1{\expandafter\LKeyset@i#1\@nil}
\def\LKeyset@i#1=#2\@nil{\texttt{#1=#2}%
  \index{#1@\texttt{#1}}\index{Keyword!#1@\texttt{#1}}}
\let\LKeyword\LKeyset
%
\newcommand\Larg [1]{{\normalfont\itshape#1\/}}
\newcommand\Larga[1]{$\langle$\Larg{#1}$\rangle$}% angles
\newcommand\Largb[1]{\lcb\Larg{#1}\rcb}          % curly brace
\newcommand\Largs[1]{\lsb\Larg{#1}\rsb}          % square brackets
\newcommand\Largr[1]{\lrb\Larg{#1}\rrb}          % round brackets
\newcommand\LBEG[1]{{\normalfont\ttfamily\bs{}begin\lcb#1\rcb}\xLenv{#1}}
\newcommand\LmBEG[1]{{\normalfont\ttfamily\bs{}begin\lcb#1\rcb}\xLmenv{#1}}
\newcommand\LEND[1]{{\normalfont\ttfamily\bs{}end\lcb#1\rcb}\xLenv{#1}}
\newcommand\LmEND[1]{{\normalfont\ttfamily\bs{}end\lcb#1\rcb}\xLmenv{#1}}
%
\DeclareRobustCommand\bs{{\normalfont\ttfamily\textbackslash}}  % \let\bslash=\bs
\DeclareRobustCommand\lcb{{\normalfont\ttfamily\textbraceleft}}
\DeclareRobustCommand\rcb{{\normalfont\ttfamily\textbraceright}}
\DeclareRobustCommand\lsb{{\normalfont\ttfamily[}}
\DeclareRobustCommand\rsb{{\normalfont\ttfamily]}}
\DeclareRobustCommand\lrb{{\normalfont\ttfamily(}}
\DeclareRobustCommand\rrb{{\normalfont\ttfamily)}}
\DeclareRobustCommand\false{{\ttfamily false}}
\DeclareRobustCommand\true{{\ttfamily true}}

%
% without brackets
\def\Coordx#1{$x_{#1}$}
\def\Coordy#1{$y_{#1}$}
\def\Coordz#1{$z_{#1}$}
\def\Coord#1{\Coordx{#1},\kern 1pt\Coordy{#1}}
\def\Coordn{\Coordx{n},\kern 1pt\Coordy{n}}
\def\CoordIII#1{\Coordx{#1},\kern 1pt\Coordy{#1},\kern 1pt\Coordz{#1}}% HjG
\def\CAny{\Coordx{},\kern 1pt\Coordy{}}
\def\CIIIAny{\Coordx{},\kern 1pt\Coordy{},\kern 1pt\Coordz{}}%  hv
% with brackets
\def\coord#1{(\Coordx{#1},\kern 1pt\Coordy{#1})}
\def\coordn{(\Coordx{n},\kern 1pt\Coordy{n})}
\def\coordiii#1{(\Coordx{#1},\kern 1pt\Coordy{#1},\kern 1pt\Coordz{#1})}% hv
\def\coordx#1{($x_{#1}$)}
\def\coordy#1{($y_{#1}$)}
\def\coordz#1{($z_{#1}$)}
\def\cAny{(\Coordx{},\kern 1pt\Coordy{})}
\def\ciiiAny{(\Coordx{},\kern 1pt\Coordy{},\kern 1pt\Coordz{})}% hv
%
\newskip\BDefaboveskip
\newskip\BDefbelowskip
\newskip\BDefinlineskip
\setlength\BDefaboveskip{0pt plus 2pt}% first-level list topsep
\setlength\BDefbelowskip{10pt}
\setlength\BDefinlineskip{6pt}
%
\newsavebox\boxdef
\newenvironment{BDef}
  {\begin{lrbox}{\boxdef}
      \def\arraystretch{1.0}
      \begin{tabular}{@{}l@{}l@{}l@{}}}
  {\end{tabular}\end{lrbox}
%
% braces around next block are needed to stop the list env checking for blank lines
% and the \aftergroups then for making sure no indentation happens ... as i said
% urg
%
   {\BCmd\fbox{\usebox\boxdef}\endBCmd}
   \aftergroup\@afterindentfalse\aftergroup\@afterheading
  }
\newenvironment{BDef*}
  {\begin{lrbox}\boxdef
      \def\arraystretch{1.0}
      \begin{tabular}{@{}l@{}l@{}l@{}}
  }
  {\end{tabular}\end{lrbox}
   {\begin{BCmd*}\fbox{\usebox\boxdef}\end{BCmd*}}
   \aftergroup\@afterindentfalse\aftergroup\@afterheading
  }
\newenvironment{BCmd}{
  \@beginparpenalty-\@lowpenalty
  \topsep\BDefaboveskip
  \fboxsep3pt
  \flushleft}
 {\@endparpenalty\@M
  \@topsepadd\BDefbelowskip
  \endflushleft}

\newenvironment{BCmd*}{
  \@beginparpenalty\@M
  \topsep\BDefinlineskip
  \fboxsep3pt
  \flushleft}
 {\@endparpenalty5000
  \endflushleft}


\def\OptArgs{\colorbox{black!20}{\texttt{[Options]}}\kern1pt}

\def\OptArg{\@ifnextchar*\OptArg@i{\OptArg@ii*}}% star version without braces
\def\OptArg@i*#1{\colorbox{black!20}{\texttt{#1}}\kern1pt}
\def\OptArg@ii*#1{\colorbox{black!20}{\texttt{[#1]}}\kern1pt}
\def\DBS{{\ttfamily\textbackslash\textbackslash}}

\def\docauthor#1{\gdef\@docauthor{#1}}
\docauthor{}
%\def\author#1{\gdef\@author{#1}\gdef\@docauthor{#1}}

\providecommand\bgImage{}
\providecommand\bgTitle{}
\providecommand\LenToUnit[1]{#1\@gobble}

\def\settitle{%
  \thispagestyle{empty}%
  \begin{titlepage}
  \newgeometry{lmargin=1cm,rmargin=1cm,bmargin=1cm,includeheadfoot}
  \ifpdf
    \AddToShipoutPicture*{\includegraphics{pst-doc.pdf}}
    \vspace*{0.3\textheight}
    \parbox{17cm}{\sffamily\RaggedRight\bfseries\huge\@title}\\[5pt]
    \parbox{15cm}{\sffamily\Large\@subtitle}

    \vspace{2cm}
    \parbox{10cm}{\sffamily\@date}

    \vfill
    \makebox[\textwidth]{\makebox(0,0){\bgImage}}
    
    \vfill
    \parbox[b]{19cm}{\sffamily\RaggedRight 
      \ifx\@docauthor\empty~\else Documentation by\fi\hfill\makebox[7cm][l]{Package author(s):}\\
      \ifx\@docauthor\empty~\else{\bfseries\tabular[t]{@{}l@{}}\@docauthor\endtabular}\fi\hfill\makebox[7cm][l]{%
        \bfseries\tabular[t]{@{}l@{}}\@author\endtabular}}
    \clearpage\restoregeometry
  \else
    \psset{unit=1cm}%
    \begin{pspicture}(1.6in,0)(23cm,21.7cm)
      \psframe[fillstyle=solid,linecolor=lightgray,fillcolor=lightgray,linestyle=solid](0,-5.75)(24,10)
      \psframe[fillstyle=solid,linecolor=Orange!85!Red,fillcolor=Orange!85!Red,linestyle=solid](0,10)(23.5,10.5)
      \psframe[fillstyle=solid,linecolor=Orange!85!Red,fillcolor=Orange!85!Red,linestyle=solid](0,21.1)(24,21.2)
      \rput[lb](4,22){\Huge\sffamily\color{Orange!65!Red}\psscalebox{2}{\textbf{PSTricks}}}
      \rput[lb](4,14.1){\parbox{17cm}{\sffamily\RaggedRight\bfseries\huge\@title}}
      \rput[lb](4,12.6){\parbox{15cm}{\sffamily\Large\@subtitle}}
      \rput[lb](4,8.5){\parbox{15cm}{\sffamily\@date}}
      \rput[lb](4,-1){\parbox[b]{19cm}{\sffamily\RaggedRight 
        \ifx\@docauthor\empty~\else Documentation by\fi\hfill\makebox[7cm][l]{Package author(s):}\\
        \ifx\@docauthor\empty~\else{\bfseries\tabular[t]{@{}l@{}}\@docauthor\endtabular}\fi\hfill\makebox[7cm][l]{%
          \bfseries\shortstack[l]{\@author}
             %\begin{tabular}[t]{@{}l@{}} \@author\end{tabular}%
      }}}
      \rput[C](11,4){\bgImage}%
    \end{pspicture}%
  \fi
  \end{titlepage}
  \setcounter{footnote}{0}%
  \global\let\thanks\relax%
  \global\let\maketitle\relax%
  \global\let\@thanks\@empty%
  \global\let\@author\@empty%
  \global\let\@docauthor\@empty%
  \global\let\@date\@empty%
  \global\let\@title\@empty%
  \global\let\@subtitle\@empty%
  \global\let\title\relax%
  \global\let\author\relax%
  \global\let\date\relax%
  \global\let\and\relax%
  \restoregeometry
}

\newdimen\fullWidth
\fullWidth=\linewidth
\advance\fullWidth by \marginparsep
\advance\fullWidth by \marginparwidth
\makeatother
%%
%% End of file `pst-doc.cls'.
