/* wnnr — Win95-style window in a terminal. Arrow keys move. q quits. */
#include <stdio.h>
#include <unistd.h>
#include <termios.h>
#include <stdlib.h>
#define W 36
static struct termios o;
static void r(void){tcsetattr(0,0,&o);fputs("\x1b[0m\x1b[?25h\x1b[2J\x1b[H",stdout);}
static void d(int x,int y){
 fputs("\x1b[0m\x1b[2J",stdout);
 printf("\x1b[%d;%dH\x1b[48;5;21;38;5;15m%-*s",y+1,x+1,W," wnnr - window         _ [] X ");
 printf("\x1b[%d;%dH\x1b[48;5;7;38;5;0m%-*s",y+2,x+1,W," File  Edit  View  Help");
 for(int j=3;j<11;j++)printf("\x1b[%d;%dH\x1b[48;5;7m%*s",y+j,x+1,W,"");
 fflush(stdout);
}
int main(void){
 struct termios t;
 tcgetattr(0,&o);t=o;t.c_lflag&=~(ICANON|ECHO);
 tcsetattr(0,0,&t);atexit(r);fputs("\x1b[?25l",stdout);
 int x=5,y=2;d(x,y);
 char b[8];int n;
 while((n=read(0,b,8))>0){
  if(*b=='q')return 0;
  if(n>=3&&b[0]==27&&b[1]=='[')switch(b[2]){
   case 'A':if(y>0)y--;break;
   case 'B':y++;break;
   case 'C':x++;break;
   case 'D':if(x>0)x--;break;
  }
  d(x,y);
 }
}
