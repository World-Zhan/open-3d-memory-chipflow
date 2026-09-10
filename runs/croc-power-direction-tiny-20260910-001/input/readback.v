module direction_fixture (clk,
    d,
    r,
    q);
 input clk;
 input d;
 input r;
 output q;

 wire coreclk;

 bondpad70_m2_ring bond (.pad(clk));
 sg13g2_IOPadIn io (.p2c(coreclk),
    .pad(clk));
 sg13g2_dfrbpq_1 ff (.RESET_B(r),
    .D(d),
    .Q(q),
    .CLK(coreclk));
endmodule
