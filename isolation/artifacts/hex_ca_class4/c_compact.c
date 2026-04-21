/* Hex-CA class-4 — compact C target for Isolation hex-ca-class4.
 * K=4 colours, 6-nbr hex, 36x18 toroid, stdout ANSI.
 * Omits search/evolve: picks rule from argv seed and renders.
 * Build: cc -O2 c_compact.c -o hex_ca
 * Run:   ./hex_ca [seed]                                     */
#include<stdio.h>
#include<stdlib.h>
#include<unistd.h>
#define K 4
#define W 36
#define H 18
#define N 16384
unsigned char R[N],G[H][W],T[H][W];
int DY[6]={-1,-1,0,0,1,1};
int DE[6]={-1,0,-1,1,-1,0},DO[6]={0,1,-1,1,0,1};
int P[4]={232,22,94,208};
int main(int c,char**v){
  srand(c>1?atoi(v[1]):1);
  for(int i=0;i<N;i++)R[i]=rand()%K;
  for(int y=0;y<H;y++)for(int x=0;x<W;x++)G[y][x]=rand()%K;
  for(int t=0;t<300;t++){
    printf("\x1b[H\x1b[J");
    for(int y=0;y<H;y++){
      if(y&1)putchar(' ');
      for(int x=0;x<W;x++)printf("\x1b[48;5;%dm  ",P[G[y][x]]);
      printf("\x1b[0m\n");
    }
    fflush(stdout);
    for(int y=0;y<H;y++){
      int*d=(y&1)?DO:DE;
      for(int x=0;x<W;x++){
        int i=G[y][x];
        for(int k=0;k<6;k++){
          int Y=(y+DY[k]+H)%H,X=(x+d[k]+W)%W;
          i=i*K+G[Y][X];
        }
        T[y][x]=R[i];
      }
    }
    for(int y=0;y<H;y++)for(int x=0;x<W;x++)G[y][x]=T[y][x];
    usleep(60000);
  }
}
